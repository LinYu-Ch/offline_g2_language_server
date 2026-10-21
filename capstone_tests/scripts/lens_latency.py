#!/usr/bin/env python3
"""Score physical end-of-speech-to-visible-G2-caption latency.

Requires real synchronized observation! Each row must use a single recording
clock (seconds from the same video/audio capture, or frames divided by FPS).
Never infer lens visibility from HTTP 200 or BLE queued events.
"""
import argparse
import csv
from collections import defaultdict
from pathlib import Path
import statistics
import json
import math

FIELDS=['trial_id','model','backend','language','audio_end_s','lens_visible_s','notes']

def percentile(values,q):
    data=sorted(values)
    if not data:raise ValueError('empty values')
    rank=(len(data)-1)*q/100
    lo=int(rank);hi=min(lo+1,len(data)-1)
    return data[lo] + (data[hi] - data[lo]) * (rank - lo)

def evaluate(rows):
    output=[]
    ids=set()
    for r in rows:
        trial=r['trial_id'].strip()
        if not trial or trial in ids:raise ValueError(f'Missing/duplicate trial ID: {trial!r}')
        ids.add(trial)
        start=float(r['audio_end_s']);end=float(r['lens_visible_s'])
        if not (math.isfinite(start) and math.isfinite(end)) or start<0 or end<start:raise ValueError(f'Invalid timing for {trial}: speech ends {start}, lens visible {end}')
        row=dict(r)
        row['latency_seconds']=round(end-start,6)
        output.append(row)
    return output

def summarize(scored):
    grouped=defaultdict(list)
    for r in scored:
        grouped[(r['model'].lower(),r['backend'].lower())].append(float(r['latency_seconds']))
    output=[]
    for (model,backend),vals in sorted(grouped.items()):
        output.append({'model':model,'backend':backend,'n':len(vals),
                       'median_lens_latency_s':round(statistics.median(vals),4),
                       'p95_lens_latency_s':round(percentile(vals,95),4),
                       'max_lens_latency_s':round(max(vals),4),
                       'within_2p5_seconds':sum(t<=2.5 for t in vals),
                       'fraction_within_2p5_seconds':round(sum(t<=2.5 for t in vals)/len(vals),4)})
    return output

def write(path,rows):
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

def plot(summary,out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    labels=[f"{s['model'].title()} {s['backend'].upper()}" for s in summary]
    y=[s['median_lens_latency_s'] for s in summary]
    p95=[s['p95_lens_latency_s'] for s in summary]
    fig,ax=plt.subplots(figsize=(9,5))
    ax.bar(labels,y,label='Median lens-visible latency')
    ax.scatter(range(len(y)),p95,marker='D',s=55,label='P95 estimate')
    ax.axhline(2.5,linestyle='--',label='2.5 s target')
    ax.set(ylabel='Seconds from speech end to caption on lens',title='Observed physical G2 caption latency')
    ax.legend();ax.tick_params(axis='x',rotation=12)
    fig.tight_layout();fig.savefig(out,dpi=170);plt.close(fig)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--annotations',required=True)
    p.add_argument('--out-dir',required=True)
    a=p.parse_args()
    with Path(a.annotations).open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        if not set(FIELDS).issubset(set(reader.fieldnames or [])):
            raise SystemExit(f'Annotations require columns {FIELDS}')
        rows=list(reader)
    if not rows:raise SystemExit('Annotations are empty. Record actual lens observations first.')
    scored=evaluate(rows);summary=summarize(scored)
    out=Path(a.out_dir);out.mkdir(parents=True,exist_ok=True)
    write(out/'g2_lens_latency_trials.csv',scored)
    write(out/'g2_lens_latency_summary.csv',summary)
    plot(summary,out/'g2_lens_latency.png')
    (out/'method.json').write_text(json.dumps({'method':'Human annotated speech end and confirmed visible G2 text on same captured audio/video timeline','note':'Physical display measurements require synchronized observation; no simulated events used.'},indent=2),encoding='utf-8')
    print('Saved actual G2 display latency graph and results in',out)
    if min(r['n'] for r in summary)<20:
        print('Caution: Small sample count; do not treat P95 as a reliable tail estimate.')

if __name__=='__main__':main()
