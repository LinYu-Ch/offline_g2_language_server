#!/usr/bin/env python3
"""Summarize REAL whisper-stream JSONL inference times and RTF; no physical G2 timing."""
import argparse
import csv
import json
from pathlib import Path
import statistics

def parse_stream(text):
    rows=[]
    for line in text.splitlines():
        try:
            obj=json.loads(line)
            if not isinstance(obj, dict) or 'dur' not in obj or 'infer_ms' not in obj:
                continue
            sec=float(obj.get('dur') or 0)
            infer=float(obj.get('infer_ms') or 0)/1000
            if sec<=0 or infer<0:continue
            rows.append({'id':obj.get('id',len(rows)),
                'audio_seconds':sec,'inference_seconds':infer,
                'inference_rtf':infer/sec,'source_text':obj.get('source',''),
                'english_text':obj.get('english','')})
        except (json.JSONDecodeError,TypeError,ValueError,AttributeError):continue
    return rows

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--jsonl',required=True)
    p.add_argument('--out-dir',required=True)
    a=p.parse_args()
    rows=parse_stream(Path(a.jsonl).read_text(encoding='utf-8-sig'))
    if not rows:raise SystemExit('No valid stream JSONL utterances found')
    out=Path(a.out_dir);out.mkdir(parents=True,exist_ok=True)
    with (out/'live_stream_inference.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    weighted=sum(r['inference_seconds'] for r in rows)/sum(r['audio_seconds'] for r in rows)
    summary={'utterances':len(rows),'median_inference_seconds':statistics.median(r['inference_seconds'] for r in rows),
       'worst_inference_seconds':max(r['inference_seconds'] for r in rows),
       'weighted_inference_rtf':weighted,
       'note':'whisper-stream infer_ms only; excludes VAD hang, queue waiting, BLE and visible G2 update'}
    (out/'live_stream_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(9,5))
    ax.plot(range(1,len(rows)+1),[r['inference_rtf'] for r in rows],marker='o')
    ax.axhline(1.0,ls='--',label='RTF 1.0')
    ax.set(xlabel='Utterance sequence',ylabel='Model inference RTF',
           title='Actual microphone pipeline inference RTF (NOT lens latency)')
    ax.legend();fig.tight_layout()
    fig.savefig(out/'live_stream_inference_rtf.png',dpi=170);plt.close(fig)
    print('Saved live stream inference measurements in',out)

if __name__=='__main__':main()
