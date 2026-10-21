"""Self-tests for CSV metrics, model comparison calculations, and WAV logic."""
import pathlib
import sys
import unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from benchmark import edit_distance, word_error_rate, char_error_rate, normalize_text, weighted_rtf, source_wer_for_language

class MetricsTests(unittest.TestCase):
    def test_wer_zero_for_exact_text(self):
        self.assertEqual(word_error_rate('hello world','hello world'),0.0)
    def test_wer_substitution(self):
        self.assertAlmostEqual(word_error_rate('the train arrives now','the train leaves now'),.25)
    def test_normalization(self):
        self.assertEqual(normalize_text('  HELLO, World! '),'hello world')
    def test_language_appropriate_source_wer(self):
        self.assertIsNone(source_wer_for_language('東京駅', '東京駅', 'ja-JP'))
        self.assertEqual(source_wer_for_language('hola mundo', 'hola mundo', 'es'), 0.0)

    def test_cer(self):
        self.assertAlmostEqual(char_error_rate('こんにちは','こんいちは'),.2)
    def test_weighted_rtf(self):
        self.assertAlmostEqual(weighted_rtf([(1,5),(9,10)]),10/15)
    def test_zero_audio_is_not_valid(self):
        with self.assertRaises(ValueError):weighted_rtf([(1,0)])

if __name__=='__main__':unittest.main()
