#!/usr/bin/env python3
"""Publication-oriented plots from one timestamped extended benchmark session."""
import argparse
import csv
import json
from pathlib import Path
import statistics

ORDER=[('base','cpu'),('base','gpu'),('small','cpu'),('small','gpu')]

def read_csv(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))

def group_trials(folder):
    groups={}
    for path in Path(folder).rglob('*_trials.csv'):
        rows=read_csv(path)
        if not rows:continue
        key=(rows[0]['model'],rows[0]['backend'])
        if any((r['model'],r['backend'])!=key for r in rows):
            raise ValueError(f'CSV contains mixed configurations: {path}')
        if key in groups:
            raise ValueError(f'Duplicate measurements for {key}; use a single session folder')
        groups[key]=rows
    return groups

def fmt(v):return f'{v:.3f}' if v is not None else ''

def summarize(folder):
    groups=group_trials(folder)
    accuracy={(r['model'],r['backend']):r for r in read_csv(Path(folder)/'accuracy_summary.csv')} if (Path(folder)/'accuracy_summary.csv').exists() else {}
    rows=[]
    for key in ORDER:
        if key not in groups:continue
        raw=groups[key]
        totals=[float(r['total_seconds']) for r in raw]
        durations=[float(r['audio_seconds']) for r in raw]
        r={'model':key[0],'backend':key[1], 'n_trials':len(raw),
           'n_unique_recordings':len(set(r['sample_id'] for r in raw)),
           'median_http_seconds':statistics.median(totals),
           'weighted_http_rtf':sum(totals)/sum(durations)}
        resource_file=Path(folder)/f'{key[0]}_{key[1]}'/'resource_summary.json'
        resource=json.loads(resource_file.read_text(encoding='utf-8')) if resource_file.exists() else {}
        if resource and resource.get('benchmark_exit_code') != 0:
            raise RuntimeError(f'Failed benchmark cannot be graphed: {resource_file}')
        for k in ('peak_container_cpu_percent','peak_container_ram_mib',
                  'peak_gpu_util_percent','peak_gpu_vram_used_mib',
                  'count_gpu_util_percent','samples'):
            r[k]=resource.get(k)
        metrics=accuracy.get(key,{})
        for k in ('mean_source_wer','mean_source_cer','corpus_bleu','corpus_chrf',
                  'n_translation_scored','n_source_cer_scored','n_non_english_source_scored'):
            r[k]=float(metrics[k]) if metrics.get(k) not in (None,'') else None
        rows.append(r)
    return rows

def generate(rows,output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    labels=[f"{r['model'].title()} {r['backend'].upper()}" for r in rows]
    managed = [
        '01_median_http_latency.png', '02_weighted_http_rtf.png',
        '03_container_ram.png', '04_gpu_vram.png',
        '05_container_cpu_utilization.png', '06_gpu_utilization.png',
        '07_source_cer.png', '08_translation_chrf.png',
        '09_translation_bleu.png',
    ]
    # A rerender should not leave graphs from metrics no longer available.
    for filename in managed:
        (output / filename).unlink(missing_ok=True)

    def bar(metric,name,title,ylabel,ref=None,unit='',multiplier=1,gpu_only=False):
        pairs=[(label,r[metric]*multiplier) for label,r in zip(labels,rows)
               if r.get(metric) is not None and (not gpu_only or r['backend']=='gpu')]
        if not pairs:return False
        fig,ax=plt.subplots(figsize=(9,5))
        plotted=[v for _,v in pairs]
        rects=ax.bar([x for x,_ in pairs],plotted)
        ylim=max(plotted)*1.24 if max(plotted)>0 else 1.0
        if ref is not None:ylim=max(ylim,ref*1.12)
        ax.set_ylim(0,ylim)
        ax.bar_label(rects,labels=[f'{v:.3f}{unit}' if v<1 else f'{v:.2f}{unit}' for v in plotted],padding=3,fontsize=9)
        if ref is not None:
            ax.axhline(ref,ls='--',label=f'RTF = {ref:g}')
            ax.legend(loc='upper right')
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.tick_params(axis='x',rotation=12)
        fig.tight_layout()
        fig.savefig(output/name,dpi=170)
        plt.close(fig)
        return True
    bar('median_http_seconds','01_median_http_latency.png',
        'Median two-pass HTTP request latency (not G2 display latency)','Seconds')
    bar('weighted_http_rtf','02_weighted_http_rtf.png',
        'Weighted two-pass HTTP real-time factor (RTF)','RTF, lower is faster',ref=1.0)
    bar('peak_container_ram_mib','03_container_ram.png',
        'Observed peak Whisper container RAM during benchmark','Container RAM (MiB)')
    bar('peak_gpu_vram_used_mib','04_gpu_vram.png',
        'Peak sampled device-wide VRAM (not Whisper-only)','GPU VRAM used (MiB)',gpu_only=True)
    bar('peak_container_cpu_percent','05_container_cpu_utilization.png',
        'Peak observed Docker container CPU utilization','Docker CPU (%) — can exceed 100% on multicore')
    # Short GPU benchmarks can yield only one or two device snapshots; a
    # utilization comparison from those samples would be misleading.
    gpu_rows = [r for r in rows if r['backend'] == 'gpu']
    if gpu_rows and all((r.get('count_gpu_util_percent') or 0) >= 3 for r in gpu_rows):
        bar('peak_gpu_util_percent','06_gpu_utilization.png',
            'Peak sampled device-wide NVIDIA GPU utilization','GPU utilization (%)',gpu_only=True)
    # An English-only smoke test cannot establish multilingual accuracy.
    if any((r.get('n_non_english_source_scored') or 0) > 0 for r in rows):
        bar('mean_source_cer','07_source_cer.png',
            'Mean source-language character error rate (unique clips)','CER (%)',unit='%',multiplier=100)
    bar('corpus_chrf','08_translation_chrf.png',
        'English translation chrF score (verified references required)','chrF (higher is better)')
    bar('corpus_bleu','09_translation_bleu.png',
        'English translation BLEU score (verified references required)','BLEU (higher is better)')
    return sorted(p.name for p in output.glob('*.png'))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',required=True)
    a=p.parse_args()
    folder=Path(a.run)
    rows=summarize(folder)
    if not rows:raise SystemExit('No *_trials.csv files found in run directory')
    with (folder/'performance_summary.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    charts=generate(rows,folder/'graphs')
    print('Created',len(charts),'graphs in',folder/'graphs')
    print('CSV summary:',folder/'performance_summary.csv')
    print('Accuracy graphs only appear when corresponding references exist.')
    print('Resource metrics: sampled Docker stats and device-wide nvidia-smi, not isolated process VRAM.')

if __name__=='__main__':main()
