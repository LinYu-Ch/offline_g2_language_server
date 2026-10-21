#!/usr/bin/env python3
"""Summarize human review of translation meaning (separate from chrF/BLEU)."""
import argparse
from collections import defaultdict
import csv
from pathlib import Path
import statistics

def score(rows):
    groups=defaultdict(list)
    for row in rows:
        num=int(row['score_1_to_5'])
        if not 1<=num<=5:raise ValueError('Scores must be 1 to 5')
        critical=row['critical_error_yes_no'].strip().lower()
        if critical not in {'yes','no'}:raise ValueError('critical_error_yes_no must be yes or no')
        groups[(row['model'].lower(),row['backend'].lower())].append((num,critical))
    return [{'model':model,'backend':backend,'n_ratings':len(v),
             'mean_rating':round(statistics.mean(x[0] for x in v),4),
             'critical_error_rate':round(sum(x[1]=='yes' for x in v)/len(v),4)}
            for (model,backend),v in sorted(groups.items())]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ratings',required=True)
    p.add_argument('--out-dir',required=True)
    a=p.parse_args()
    with Path(a.ratings).open(encoding='utf-8-sig',newline='') as f:
        rows=list(csv.DictReader(f))
    if not rows:raise SystemExit('Fill in real blinded human ratings first; file has no rows')
    scores=score(rows)
    out=Path(a.out_dir);out.mkdir(parents=True,exist_ok=True)
    with (out/'human_translation_summary.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(scores[0]));w.writeheader();w.writerows(scores)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    labels=[f"{s['model'].title()} {s['backend'].upper()}" for s in scores]
    for col,name,ylabel in [('mean_rating','human_mean_translation_score.png','Human meaning fidelity score (1-5)'),
                            ('critical_error_rate','human_critical_error_rate.png','Fraction of reviewed translations with critical error')]:
        fig,ax=plt.subplots(figsize=(8,4))
        vals=[r[col] for r in scores]
        ax.bar(labels,vals)
        ax.set_ylim(0,5 if col=='mean_rating' else 1)
        ax.set(ylabel=ylabel,title='Human-reviewed translation quality')
        fig.tight_layout();fig.savefig(out/name,dpi=170);plt.close(fig)
    print('Human review graphs saved to',out)

if __name__=='__main__':main()
