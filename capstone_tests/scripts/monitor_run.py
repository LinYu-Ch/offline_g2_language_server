#!/usr/bin/env python3
"""Run an existing benchmark while sampling Docker container RAM/CPU and NVIDIA GPU.

Measurements are observational snapshots: container RAM is not host-wide RAM;
NVIDIA SMI GPU statistics are device-wide, not necessarily attributable to Whisper.
"""
import argparse
import csv
import datetime as dt
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

FIELDS = ['elapsed_s','utc','container_cpu_percent','container_ram_mib',
          'gpu_util_percent','gpu_vram_used_mib','docker_error','nvidia_error']

def size_to_mib(raw):
    """Parse Docker human-readable memory quantity to MiB."""
    match = re.match(r'^\s*([\d.]+)\s*([a-zA-Z]+)\s*$', raw)
    if not match:
        raise ValueError(f'Unknown Docker memory format: {raw!r}')
    size, unit = float(match.group(1)), match.group(2).lower()
    factors = {'b':1/1048576, 'kb':1000/1048576, 'mb':1e6/1048576,
               'gb':1e9/1048576, 'tb':1e12/1048576,
               'kib':1/1024, 'mib':1, 'gib':1024, 'tib':1024**2}
    if unit not in factors:
        raise ValueError(f'Unexpected memory unit {unit!r}')
    return size * factors[unit]

def parse_docker_stats(text):
    info = json.loads(text.strip().splitlines()[-1])
    return float(info['CPUPerc'].strip().rstrip('%')), size_to_mib(info['MemUsage'].split('/')[0])

def parse_nvidia_stats(text):
    first = text.strip().splitlines()[0].split(',')
    if len(first) < 2:
        raise ValueError('Unexpected nvidia-smi output')
    return float(first[0].strip()), float(first[1].strip())

def command_output(args, timeout=10):
    r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, timeout=timeout, check=False)
    if r.returncode:
        raise RuntimeError(f'{args[0]} exit {r.returncode}: {r.stderr.strip()[:200]}')
    return r.stdout

def read_snapshot(container):
    row = {name:'' for name in FIELDS}
    try:
        output = command_output(['docker','stats','--no-stream',
            '--format','{{json .}}',container])
        cpu, mem = parse_docker_stats(output)
        row.update(container_cpu_percent=round(cpu,3),container_ram_mib=round(mem,3))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, IndexError) as exc:
        row['docker_error'] = str(exc)[:200]
    try:
        output = command_output(['nvidia-smi',
            '--query-gpu=utilization.gpu,memory.used',
            '--format=csv,noheader,nounits'])
        gpu, vram = parse_nvidia_stats(output)
        row.update(gpu_util_percent=round(gpu,3),gpu_vram_used_mib=round(vram,3))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, IndexError) as exc:
        row['nvidia_error'] = str(exc)[:200]
    return row

def summarise(rows,exit_code,command,model,backend):
    metric_fields=['container_cpu_percent','container_ram_mib','gpu_util_percent','gpu_vram_used_mib']
    out={'model':model,'backend':backend,'benchmark_exit_code':exit_code,
         'command':command,'samples':len(rows),
         'metric_note':'Docker container CPU/RAM and device-wide nvidia-smi GPU/VRAM snapshots; peak is sampled, not hardware instantaneous peak.'}
    for col in metric_fields:
        nums=[float(r[col]) for r in rows if r[col] != '']
        out['peak_'+col]=round(max(nums),3) if nums else None
        out['mean_'+col]=round(sum(nums)/len(nums),3) if nums else None
        out['count_'+col]=len(nums)
    out['first_gpu_vram_used_mib']=next((float(r['gpu_vram_used_mib']) for r in rows if r['gpu_vram_used_mib']!=''),None)
    return out

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--container',required=True,help='Running Whisper container name or ID')
    p.add_argument('--out-dir',required=True)
    p.add_argument('--model',required=True,choices=['base','small'])
    p.add_argument('--backend',required=True,choices=['cpu','gpu'])
    p.add_argument('--interval',type=float,default=1.0)
    p.add_argument('command',nargs=argparse.REMAINDER,help='Pass -- then command to run')
    a=p.parse_args()
    if a.interval < 0.5: p.error('--interval must be >= 0.5s')
    command=a.command[1:] if a.command and a.command[0]=='--' else a.command
    if not command: p.error('Specify a benchmark command after --')
    folder=Path(a.out_dir)
    folder.mkdir(parents=True,exist_ok=True)
    rows=[]
    lock=threading.Lock()
    stop=threading.Event()
    start=time.monotonic()
    def sample():
        while not stop.is_set():
            row=read_snapshot(a.container)
            row['elapsed_s']=round(time.monotonic()-start,3)
            row['utc']=dt.datetime.now(dt.timezone.utc).isoformat()
            with lock: rows.append(row)
            stop.wait(a.interval)
    worker=threading.Thread(target=sample,daemon=True)
    worker.start()
    print('Monitoring Docker container and NVIDIA GPU while running:', ' '.join(command),flush=True)
    exit_code=1
    try:
        with (folder/'benchmark_stdout.log').open('w',encoding='utf-8') as stdout, \
             (folder/'benchmark_stderr.log').open('w',encoding='utf-8') as stderr:
            result=subprocess.run(command,stdout=stdout,stderr=stderr,check=False)
            exit_code=result.returncode
    finally:
        stop.set()
        worker.join(timeout=14)
        with (folder/'resource_samples.csv').open('w',encoding='utf-8',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=FIELDS)
            writer.writeheader();writer.writerows(rows)
        summary=summarise(rows,exit_code,command,a.model,a.backend)
        (folder/'resource_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        print('Resource snapshots:',folder/'resource_samples.csv',flush=True)
        print('Resource summary:',folder/'resource_summary.json',flush=True)
        print('Benchmark output:',folder/'benchmark_stdout.log',flush=True)
        print('Return code:',exit_code,flush=True)
    if exit_code == 0 and summary['count_container_ram_mib'] == 0:
        print('ERROR: Docker RAM snapshots unavailable. Inspect docker_error in resource_samples.csv.', file=sys.stderr)
        return 3
    if exit_code == 0 and a.backend == 'gpu' and summary['count_gpu_vram_used_mib'] == 0:
        print('ERROR: GPU VRAM snapshots unavailable. Inspect nvidia_error in resource_samples.csv.', file=sys.stderr)
        return 3
    if len(rows) < 3:
        print('CAUTION: fewer than 3 resource snapshots; peak measurements may miss spikes.', file=sys.stderr)
    return exit_code

if __name__=='__main__':
    sys.exit(main())
