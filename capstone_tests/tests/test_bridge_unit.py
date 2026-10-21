"""Unit tests for the ACTUAL repo's whisper.cpp/g2_bridge.py, no hardware needed."""
import importlib.util
import json
import pathlib
import unittest
from unittest.mock import MagicMock, patch

REPO = pathlib.Path(__file__).resolve().parents[2]
BRIDGE = REPO / 'whisper.cpp' / 'g2_bridge.py'
if not BRIDGE.is_file():
    raise FileNotFoundError(f'Place capstone_tests/ inside the cloned repository; missing {BRIDGE}')
spec = importlib.util.spec_from_file_location('capstone_g2_bridge', BRIDGE)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

class CaptionWrapTests(unittest.TestCase):
    def test_empty_window(self):
        self.assertEqual(bridge.wrap([],34,6,950),'')

    def test_newest_utterances_remain(self):
        self.assertEqual(bridge.wrap(['old','middle','new'],20,2,950),'middle\nnew')

    def test_word_boundary_wrapping(self):
        self.assertEqual(bridge.wrap(['one two three four'],7,6,950),'one two\nthree\nfour')

    def test_utf8_byte_ceiling(self):
        for line in ['日本語テキスト'*80, 'hello 🌍'*100, 'café '*200]:
            result=bridge.wrap([line],1000,6,95)
            self.assertLessEqual(len(result.encode('utf-8')),95)
            self.assertEqual(result.encode('utf-8').decode('utf-8'),result)

    def test_older_lines_trim_before_latest(self):
        txt=bridge.wrap(['outdated caption','new caption'],80,6,15)
        self.assertLessEqual(len(txt.encode('utf-8')),15)
        self.assertEqual(txt,'new caption')

class DisplayUnitTests(unittest.TestCase):
    def test_push_duplicate_skips_http(self):
        disp=bridge.Display('http://127.0.0.1:8765/api/display',2)
        disp.shown='already on display'
        with patch.object(disp,'_connect') as connect:
            self.assertTrue(disp.push('already on display'))
            connect.assert_not_called()

    def test_bearer_header_and_json(self):
        disp=bridge.Display('http://127.0.0.1:8765/api/display',2,token='example')
        response=MagicMock(status=200)
        response.read.return_value=b'{}'
        connection=MagicMock()
        connection.getresponse.return_value=response
        with patch('http.client.HTTPConnection',return_value=connection):
            self.assertTrue(disp.push('こんにちは'))
        args=connection.request.call_args
        self.assertEqual(args.args[0],'POST')
        self.assertEqual(args.args[1],'/api/display')
        self.assertEqual(json.loads(args.kwargs['body'])['text'],'こんにちは')
        self.assertEqual(args.kwargs['headers']['Authorization'],'Bearer example')

if __name__=='__main__':unittest.main()
