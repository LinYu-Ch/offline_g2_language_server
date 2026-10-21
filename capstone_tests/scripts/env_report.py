#!/usr/bin/env python3
"""Record reproducibility metadata (not a hardware performance benchmark)."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]

def cmd(*args):
    try:
        result = subprocess.run(args,capture_output=True,text=True,timeout=15,check=False)
        return (result.stdout.strip() or None) if result.returncode==0 else None
    except (OSError,subprocess.TimeoutExpired):
        return None

def sha(path):
    if not path.is_file():return None
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',required=True)
    a=parser.parse_args()
    dest=Path(a.out)
    if not dest.is_absolute():dest=REPO/dest
    dest.parent.mkdir(parents=True,exist_ok=True)
    d={
      'created_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
      'git_commit':cmd('git','-C',str(REPO),'rev-parse','HEAD'),
      'git_branch':cmd('git','-C',str(REPO),'branch','--show-current'),
      'os':platform.platform(),
      'cpu_description':platform.processor(),
      'python':sys.version,
      'docker_version':cmd('docker','--version'),
      'gpu_info':cmd('nvidia-smi','--query-gpu=name,driver_version,memory.total,compute_cap','--format=csv,noheader'),
      'whisper_base_sha256':sha(REPO/'whisper.cpp'/'models'/'ggml-base.bin'),
      'whisper_small_sha256':sha(REPO/'whisper.cpp'/'models'/'ggml-small.bin'),
      'note':'File hashes identify tested model bytes; compare with trusted upstream hashes to verify authenticity.'
    }
    dest.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(f'Environment metadata saved to {dest}')

if __name__=='__main__':main()
