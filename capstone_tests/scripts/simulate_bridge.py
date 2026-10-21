#!/usr/bin/env python3
"""Replay Whisper JSONL through the real bridge into a MOCK HTTP gateway.

Times only stdin injection -> HTTP request received. No microphone, VAD,
Whisper inference, BLE packet transmission, or physical G2 rendering is measured.
"""
import argparse
import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

class GatewayServer(ThreadingHTTPServer):
    allow_reuse_address=True
    daemon_threads=True
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.events=[]
        self.lock=threading.Lock()

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path!='/api/display':
            self.send_error(404);return
        try:
            n=int(self.headers.get('Content-Length','0'))
            obj=json.loads(self.rfile.read(n))
            text=str(obj.get('text',''))
        except (ValueError,TypeError):
            self.send_error(400);return
        with self.server.lock:
            self.server.events.append({'time':time.monotonic(),'text':text})
        body=b'{"status":"ok"}'
        self.send_response(200);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)));self.end_headers()
        self.wfile.write(body)
    def log_message(self,*args):pass

def simulate(input_path,out,pace=0.65,timeout=3.0):
    objlist=[]
    for text in Path(input_path).read_text(encoding='utf-8-sig').splitlines():
        if text.strip() and text.lstrip().startswith('{'):
            obj=json.loads(text)
            expected=str(obj.get('english') or obj.get('source') or '').strip()
            if expected: objlist.append((obj,expected))
    if not objlist:raise ValueError('No valid utterance JSONL messages with english/source text')
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    server=GatewayServer(('127.0.0.1',0),Handler)
    server_thread=threading.Thread(target=server.serve_forever,daemon=True)
    server_thread.start()
    bridge=Path(__file__).resolve().parents[2]/'whisper.cpp'/'g2_bridge.py'
    if not bridge.exists():raise FileNotFoundError(bridge)
    cmd=[sys.executable,str(bridge),'--url',f'http://127.0.0.1:{server.server_port}/api/display',
         '--no-lag-drop','--max-cols','5000','--max-lines','10','--rate','0.20']
    result=[]
    proc=None
    try:
        with (out/'bridge_stderr.log').open('w',encoding='utf-8') as log:
            proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=log,
                                  text=True,bufsize=1)
            time.sleep(0.4)
            for idx,(obj,expected) in enumerate(objlist):
                if proc.poll() is not None:raise RuntimeError('Bridge terminated unexpectedly')
                send=time.monotonic()
                proc.stdin.write(json.dumps(obj,ensure_ascii=False)+'\n')
                proc.stdin.flush()
                found=None
                end=send+timeout
                target=' '.join(expected.split())
                while time.monotonic()<end:
                    with server.lock: events=list(server.events)
                    for event in events:
                        if event['time']>=send and target in ' '.join(event['text'].split()):
                            found=event;break
                    if found:break
                    time.sleep(0.02)
                result.append({'utterance_index':idx,'utterance_id':obj.get('id',idx),
                    'status':'accepted_by_mock_gateway' if found else 'not_observed',
                    'injection_to_mock_http_seconds':round(found['time']-send,5) if found else '',
                    'expected_text':expected,'note':'NO physical G2; starts after a JSONL result exists'})
                time.sleep(max(0,pace))
            proc.stdin.close()
            try:proc.wait(timeout=4)
            except subprocess.TimeoutExpired:proc.terminate();proc.wait(timeout=3)
    finally:
        if proc is not None and proc.poll() is None:proc.kill();proc.wait(timeout=3)
        server.shutdown();server.server_close()
    with (out/'mock_gateway_latency.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=list(result[0]));writer.writeheader();writer.writerows(result)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    delivered=[r for r in result if r['status']=='accepted_by_mock_gateway']
    if delivered:
        fig,ax=plt.subplots(figsize=(8,4))
        ax.bar([str(r['utterance_index']) for r in delivered],
               [float(r['injection_to_mock_http_seconds']) for r in delivered])
        ax.set(xlabel='Injected utterance index',ylabel='Seconds',
               title='JSONL injection to mock HTTP gateway (NOT physical G2 latency)')
        fig.tight_layout();fig.savefig(out/'mock_gateway_latency.png',dpi=170);plt.close(fig)
    print(f'Mock gateway received {len(delivered)} / {len(result)} caption updates. Saved to {out}')
    print('WARNING: NOT microphone-to-lens or end-to-end user latency.')
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--jsonl',required=True)
    p.add_argument('--out-dir',required=True)
    p.add_argument('--pace',type=float,default=0.65)
    a=p.parse_args()
    simulate(a.jsonl,a.out_dir,a.pace)

if __name__=='__main__':main()
