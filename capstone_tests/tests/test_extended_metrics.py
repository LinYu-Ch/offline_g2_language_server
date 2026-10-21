import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1] / 'extended'
sys.path.insert(0,str(HERE))
from accuracy_report import calculate
from lens_latency import evaluate,summarize,percentile
from live_stream_report import parse_stream
from monitor_run import parse_docker_stats,parse_nvidia_stats,size_to_mib,summarise
from plot_extended import summarize as graph_summary

class ResourceTest(unittest.TestCase):
    def test_docker_memory(self):
        self.assertAlmostEqual(size_to_mib('1.5 GiB'),1536)
        self.assertAlmostEqual(size_to_mib('500 MB'),500e6/1048576)
    def test_docker_cpu_can_exceed_100(self):
        cpu,mem=parse_docker_stats(json.dumps({'CPUPerc':'132.40%','MemUsage':'245.3MiB / 7.5GiB'}))
        self.assertEqual(cpu,132.4)
        self.assertAlmostEqual(mem,245.3)
    def test_nvidia_parsing(self):
        util,mem=parse_nvidia_stats('66, 1200\n')
        self.assertEqual((util,mem),(66.,1200.))
    def test_missing_metric_is_not_zero(self):
        s=summarise([{'container_cpu_percent':'','container_ram_mib':'','gpu_util_percent':'','gpu_vram_used_mib':''}],0,['python'],'base','cpu')
        self.assertIsNone(s['peak_container_ram_mib'])

class AccuracyTest(unittest.TestCase):
    def test_repeats_not_independent_samples(self):
        rows=[{'model':'base','backend':'gpu','sample_id':'es1','language':'es',
              'reference_source':'hola mundo','reference_english':'hello world',
              'source_prediction':'hola mundo','english_prediction':'hello world'} for _ in range(5)]
        samples,summary=calculate(rows,use_sacrebleu=False)
        self.assertEqual(len(samples),1)
        self.assertEqual(summary[0]['n_unique_samples'],1)
        self.assertEqual(summary[0]['mean_source_cer'],0)
    def test_cjk_wer_is_omitted(self):
        samples,summary=calculate([{'model':'small','backend':'gpu',
             'sample_id':'ja1','language':'ja','reference_source':'東京駅',
             'reference_english':'Tokyo Station','source_prediction':'東京駅',
             'english_prediction':'Tokyo Station'}],use_sacrebleu=False)
        self.assertIsNone(samples[0]['source_wer'])
        self.assertEqual(samples[0]['source_cer'],0)
    def test_missing_translation_reference_cannot_be_scored(self):
        samples,summary=calculate([{'model':'base','backend':'cpu','sample_id':'1',
            'language':'en','reference_source':'hello','reference_english':'',
            'source_prediction':'hello','english_prediction':'hello'}],use_sacrebleu=False)
        self.assertEqual(summary[0]['n_translation_scored'],0)
        self.assertIsNone(summary[0]['corpus_chrf'])

class LensLatencyTest(unittest.TestCase):
    def test_latency_from_same_clock(self):
        rows=evaluate([{'trial_id':'t1','model':'small','backend':'gpu','language':'es',
                        'audio_end_s':'1.5','lens_visible_s':'2.1','notes':''}])
        self.assertAlmostEqual(rows[0]['latency_seconds'],0.6)
        self.assertEqual(summarize(rows)[0]['within_2p5_seconds'],1)
    def test_negative_time_rejected(self):
        with self.assertRaises(ValueError):
            evaluate([{'trial_id':'a','model':'base','backend':'cpu','audio_end_s':'3.0','lens_visible_s':'2.0'}])
    def test_nonfinite_time_rejected(self):
        with self.assertRaises(ValueError):
            evaluate([{'trial_id': 'nan', 'model': 'base', 'backend': 'cpu',
                       'audio_end_s': 'nan', 'lens_visible_s': '3.0'}])

    def test_percentile(self):
        self.assertEqual(percentile([1,2,3,4,5],50),3)
        self.assertEqual(percentile([1,2,3,4,5],100),5)
        self.assertEqual(percentile([2.4],95),2.4)

class StreamTest(unittest.TestCase):
    def test_missing_inference_time_is_not_a_measurement(self):
        self.assertEqual(parse_stream(json.dumps({'dur': 3, 'english': 'hello'})), [])

    def test_jsonl_filters_logs(self):
        rows=parse_stream('noise\n'+json.dumps({'id':3,'dur':2,'infer_ms':600,'english':'hi'})+'\n')
        self.assertEqual(len(rows),1)
        self.assertAlmostEqual(rows[0]['inference_rtf'],.3)

class GraphingTest(unittest.TestCase):
    def test_no_data_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(graph_summary(d),[])

if __name__=='__main__': unittest.main()
