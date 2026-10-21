#!/usr/bin/env python3
"""Whisper Base/Small repeatable *HTTP server* benchmark. Stdlib only.

Important: both passes are independently requested from whisper-server. Reported
latency is round-trip time (upload + queuing + inference + response), NOT
whisper-stream's infer_ms or lens-visible caption latency.
"""
import argparse
import csv
import datetime as dt
import hashlib
import http.client
import json
from pathlib import Path
import re
import statistics
import time
import urllib.parse
import wave

ROOT = Path(__file__).resolve().parents[1]
# WER is not comparable with ordinary whitespace tokenization for these languages.
WORDLESS_LANGUAGES = {'ja', 'zh', 'ko', 'th', 'lo', 'my'}


def source_wer_for_language(reference, prediction, language):
    if language.lower().split('-')[0] in WORDLESS_LANGUAGES:
        return None
    return word_error_rate(reference, prediction)
COLUMNS=['timestamp_utc','model','backend','sample_id','language','repeat','audio_seconds',
         'source_seconds','english_seconds','total_seconds','rtf','source_wer','source_cer',
         'english_wer','english_cer','source_prediction','english_prediction','reference_source','reference_english','file_sha256',
         'beam_size','endpoint','metric_note']

def normalize_text(s):
    # Basic, documented normalization. Keep multilingual letters/digits;
    # this is not language-specific tokenization and is not a definitive Japanese WER.
    s=str(s).lower()
    s=''.join(c if c.isalnum() or c.isspace() else ' ' for c in s)
    return ' '.join(s.split())

def edit_distance(a,b):
    prev=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        current=[i]
        for j,y in enumerate(b,1):
            current.append(min(current[-1]+1,prev[j]+1,prev[j-1]+(x!=y)))
        prev=current
    return prev[-1]

def word_error_rate(ref,hyp):
    a=normalize_text(ref).split()
    if not a:return None
    return edit_distance(a,normalize_text(hyp).split())/len(a)

def char_error_rate(ref,hyp):
    a=normalize_text(ref).replace(' ','')
    if not a:return None
    b=normalize_text(hyp).replace(' ','')
    return edit_distance(a,b)/len(a)

def weighted_rtf(pairs):
    total=sum(d for t,d in pairs)
    if total<=0:raise ValueError('audio duration must be positive')
    return sum(t for t,d in pairs)/total

def probe_wav(path):
    with wave.open(str(path),'rb') as f:
        if f.getnchannels()!=1 or f.getsampwidth()!=2 or f.getframerate()!=16000:
            raise ValueError(f'{path}: expected 16kHz mono 16-bit PCM WAV')
        if f.getcomptype()!='NONE':raise ValueError(f'{path}: expected uncompressed PCM WAV')
        duration=f.getnframes()/f.getframerate()
        if duration<=0:raise ValueError(f'{path}: WAV contains no audio')
        return duration

def multipart_body(wav_bytes,filename,params):
    boundary='----CapstoneWhisperBenchmark4d52'
    body=bytearray()
    for key,value in [('file',(filename,wav_bytes,'audio/wav'))]+list(params.items()):
        body.extend(f'--{boundary}\r\n'.encode('ascii'))
        if key=='file':
            body.extend(f'Content-Disposition: form-data; name="file"; filename="{Path(filename).name}"\r\nContent-Type: audio/wav\r\n\r\n'.encode('utf-8'))
            body.extend(wav_bytes)
        else:
            body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n{value}'.encode('utf-8'))
        body.extend(b'\r\n')
    body.extend(f'--{boundary}--\r\n'.encode('ascii'))
    return bytes(body),f'multipart/form-data; boundary={boundary}'

def infer(url,wav_bytes,filename,lang,translate,beam,timeout):
    p=urllib.parse.urlparse(url)
    params={'language':lang,'translate':'true' if translate else 'false',
            'beam_size':str(beam),'response_format':'json'}
    data,content_type=multipart_body(wav_bytes,filename,params)
    conn=http.client.HTTPConnection(p.hostname,p.port or 80,timeout=timeout)
    start=time.perf_counter()
    try:
        conn.request('POST',p.path or '/inference',body=data,headers={'Content-Type':content_type,'Content-Length':str(len(data))})
        res=conn.getresponse()
        text=res.read()
        elapsed=time.perf_counter()-start
        if res.status!=200:raise RuntimeError(f'HTTP {res.status}: {text[:350]!r}')
        obj=json.loads(text)
        if not isinstance(obj.get('text'),str):raise RuntimeError(f'Unexpected response: {str(obj)[:300]}')
        return obj['text'].strip(),elapsed
    finally:conn.close()

def load_samples(manifest):
    with manifest.open(newline='',encoding='utf-8-sig') as f:
        reader=csv.DictReader(f)
        expected={'sample_id','audio_file','language','reference_source','reference_english'}
        if not expected.issubset(set(reader.fieldnames or [])):
            raise ValueError(f'manifest requires columns {sorted(expected)}')
        rows=list(reader)
    if not rows:raise ValueError('manifest has no recordings')
    files=[]
    seen_ids=set()
    for row in rows:
        sample_id=(row['sample_id'] or '').strip()
        if not sample_id or sample_id in seen_ids:
            raise ValueError(f'Missing or duplicate sample_id: {sample_id!r}')
        seen_ids.add(sample_id)
        if not (row['language'] or '').strip():
            raise ValueError(f'{sample_id}: missing language')
        if not (row['audio_file'] or '').strip():
            raise ValueError(f'{sample_id}: missing audio_file')
        path=(ROOT/row['audio_file']).resolve()
        if not path.is_file():raise FileNotFoundError(f'{row["sample_id"]}: missing {path}')
        files.append((row,path,probe_wav(path)))
    return files

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--manifest',default='capstone_tests/fixtures/manifest_smoke.csv')
    ap.add_argument('--model',required=True,choices=['base','small'])
    ap.add_argument('--backend',required=True,choices=['cpu','gpu'])
    ap.add_argument('--out',required=True)
    ap.add_argument('--repeats',type=int,default=3)
    ap.add_argument('--warmups',type=int,default=1)
    ap.add_argument('--beam-size',type=int,default=5)
    ap.add_argument('--url',default='http://127.0.0.1:8080/inference')
    ap.add_argument('--timeout',type=int,default=300)
    args=ap.parse_args()
    if args.repeats<1 or args.warmups<0 or args.beam_size<1:ap.error('invalid repeats/warmups/beam-size')
    manifest=Path(args.manifest)
    if not manifest.is_absolute():manifest=ROOT/manifest
    samples=load_samples(manifest)
    out=Path(args.out)
    if not out.is_absolute():out=ROOT/out
    out.parent.mkdir(parents=True,exist_ok=True)
    for row,path,duration in samples:
        print(f'Loaded {row["sample_id"]}: {duration:.2f}s, {path.name}')
    first,first_path,_=samples[0]
    print(f'Warmups: {args.warmups}, these are excluded from recorded metrics',flush=True)
    for i in range(args.warmups):
        raw=first_path.read_bytes()
        # Only warm-ups may retry transient host/Docker socket resets.
        # Never retry or silently discard measured trials: doing so would
        # bias the latency distributions reported for the capstone.
        for attempt in range(1, 4):
            try:
                infer(args.url,raw,first_path.name,first['language'],False,args.beam_size,args.timeout)
                infer(args.url,raw,first_path.name,first['language'],True,args.beam_size,args.timeout)
                break
            except (OSError, http.client.HTTPException) as exc:
                if attempt == 3:
                    raise RuntimeError('Whisper warm-up failed after 3 attempts. '
                                       'Check server logs, model readiness, and Windows network filters.') from exc
                print(f'Warm-up connection failed ({type(exc).__name__}: {exc}); '
                      f'retrying after {attempt * 2}s ({attempt}/3)',flush=True)
                time.sleep(attempt * 2)
    rows=[]
    for row,path,duration in samples:
        raw=path.read_bytes()
        filehash=hashlib.sha256(raw).hexdigest()
        for rep in range(1,args.repeats+1):
            source,t1=infer(args.url,raw,path.name,row['language'],False,args.beam_size,args.timeout)
            english,t2=infer(args.url,raw,path.name,row['language'],True,args.beam_size,args.timeout)
            record={'timestamp_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
              'model':args.model,'backend':args.backend,'sample_id':row['sample_id'],
              'language':row['language'],'repeat':rep,'audio_seconds':round(duration,6),
              'source_seconds':round(t1,6),'english_seconds':round(t2,6),
              'total_seconds':round(t1+t2,6),'rtf':round((t1+t2)/duration,6),
              'source_wer':source_wer_for_language(row['reference_source'],source,row['language']),
              'source_cer':char_error_rate(row['reference_source'],source),
              'english_wer':word_error_rate(row['reference_english'],english),
              'english_cer':char_error_rate(row['reference_english'],english),
              'source_prediction':source,'english_prediction':english,
              'reference_source':row['reference_source'],
              'reference_english':row['reference_english'],
              'file_sha256':filehash,'beam_size':args.beam_size,'endpoint':args.url,
              'metric_note':'two sequential HTTP round-trips; not actual display latency'}
            rows.append(record)
            print(f'{args.model}/{args.backend} {row["sample_id"]} repeat={rep}: '
                  f'source={t1:.2f}s translation={t2:.2f}s RTF={record["rtf"]:.2f}',flush=True)
    with out.open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=COLUMNS)
        writer.writeheader();writer.writerows(rows)
    print(f'Wrote {len(rows)} trials to {out}')
    print(f'Median total HTTP time = {statistics.median(r["total_seconds"] for r in rows):.3f}s')
    print(f'Weighted HTTP RTF = {weighted_rtf([(r["total_seconds"],r["audio_seconds"]) for r in rows]):.3f}')

if __name__=='__main__':main()
