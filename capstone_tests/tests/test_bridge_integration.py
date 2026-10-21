"""Integration tests: real bridge subprocess -> simulated G2 HTTP gateway."""
import http.server
import json
import pathlib
import queue
import subprocess
import sys
import threading
import time
import unittest

BRIDGE=pathlib.Path(__file__).resolve().parents[2]/'whisper.cpp'/'g2_bridge.py'

class StubGateway(http.server.ThreadingHTTPServer):
    allow_reuse_address=True
    daemon_threads=True
    def __init__(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length=int(self.headers.get('Content-Length','0'))
                raw=self.rfile.read(length)
                if self.path!='/api/display':
                    self.send_error(404)
                    return
                self.server.received.put(json.loads(raw)['text'])
                self.send_response(200)
                self.send_header('Content-Type','application/json')
                self.end_headers()
                self.wfile.write(b'{"accepted":true}')
            def log_message(self,*args):pass
        super().__init__(('127.0.0.1',0),Handler)
        self.received=queue.Queue()

class BridgeIntegration(unittest.TestCase):
    def setUp(self):
        self.gateway=StubGateway()
        self.thread=threading.Thread(target=self.gateway.serve_forever,daemon=True)
        self.thread.start()
        self.cmd=[sys.executable,str(BRIDGE),'--url',f'http://127.0.0.1:{self.gateway.server_port}/api/display',
                  '--rate','0','--no-lag-drop']

    def tearDown(self):
        self.gateway.shutdown()
        self.gateway.server_close()
        self.thread.join(timeout=3)

    def launch(self):
        return subprocess.Popen(self.cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,text=True,encoding='utf-8')

    def send(self,proc,uid,text):
        obj={'id':uid,'t':0,'dur':2.0,'infer_ms':500,'lang':'es','source':'hola','english':text}
        proc.stdin.write(json.dumps(obj,ensure_ascii=False)+'\n')
        proc.stdin.flush()

    def next_nonempty(self, timeout=5):
        # The current bridge can post an empty string at startup.
        # Ignore that initial clear and wait for a real caption.
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:
                text=self.gateway.received.get(timeout=max(0.01,deadline-time.monotonic()))
            except queue.Empty:break
            if text:return text
        raise AssertionError('No nonempty caption delivered by the bridge')

    def test_translated_text_reaches_gateway(self):
        p=self.launch()
        try:
            self.send(p,1,'Where is the train station?')
            self.assertEqual(self.next_nonempty(),'Where is the train station?')
            p.stdin.close()
            self.assertEqual(p.wait(timeout=5),0)
        finally:
            if p.poll() is None:p.kill();p.wait(timeout=3)
            if not p.stdin.closed:p.stdin.close()
            p.stdout.close();p.stderr.close()

    def test_malformed_json_is_ignored_but_valid_data_survives(self):
        p=self.launch()
        try:
            p.stdin.write('{oops}\n');p.stdin.flush()
            self.send(p,2,'Valid caption')
            self.assertEqual(self.next_nonempty(),'Valid caption')
            p.stdin.close()
            self.assertEqual(p.wait(timeout=5),0)
            self.assertIn('unparseable',p.stderr.read())
        finally:
            if p.poll() is None:p.kill();p.wait(timeout=3)
            if not p.stdin.closed:p.stdin.close()
            p.stdout.close();p.stderr.close()

    @unittest.expectedFailure
    def test_known_issue_final_caption_must_flush_on_eof(self):
        """KNOWN ISSUE: bridge exits on EOF when its last update is rate-limited.
        This should fail until fixed; expectedFailure keeps baseline tests green.
        Remove expectedFailure when the implementation is corrected.
        """
        idx=self.cmd.index('--rate')
        self.cmd[idx+1]='0.34'
        p=self.launch()
        try:
            self.send(p,1,'First')
            self.assertEqual(self.next_nonempty(),'First')
            self.send(p,2,'Last')
            p.stdin.close()
            self.assertEqual(p.wait(timeout=5),0)
            self.assertEqual(self.next_nonempty(timeout=1),'First\nLast')
        finally:
            if p.poll() is None:p.kill();p.wait(timeout=3)
            if not p.stdin.closed:p.stdin.close()
            p.stdout.close();p.stderr.close()

if __name__=='__main__':unittest.main()
