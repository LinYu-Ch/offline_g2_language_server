#!/usr/bin/env python3
"""Evaluate real model predictions in benchmark CSVs using per-sample references.

Repeats of the same recording are NOT counted as independent samples. Each
(model,backend,sample_id) uses the most common model output across its repeats.
Source WER is omitted for languages without conventional whitespace word breaks.
BLEU/chrF use sacrebleu; these are text-reference metrics, NOT semantic truth.
"""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from benchmark import word_error_rate, char_error_rate, WORDLESS_LANGUAGES

ORDER=[('base','cpu'),('base','gpu'),('small','cpu'),('small','gpu')]

def modal_output(rows,key):
    values=[r.get(key,'').strip() for r in rows]
    return Counter(values).most_common(1)[0][0]

def load_benchmark_files(directory):
    rows=[]
    for file in sorted(Path(directory).rglob('*_trials.csv')):
        with file.open(newline='',encoding='utf-8-sig') as f:
            rows.extend(list(csv.DictReader(f)))
    return rows

def calculate(rows, use_sacrebleu=True):
    try:
        import sacrebleu
    except ImportError:
        sacrebleu=None
    if use_sacrebleu and sacrebleu is None:
        raise RuntimeError('sacrebleu is required. Run: python -m pip install -r capstone_tests/extended/requirements.txt')
    grouped=defaultdict(list)
    for row in rows:
        if not all(k in row for k in ['sample_id','model','backend','language','source_prediction','english_prediction']):
            continue
        grouped[(row['model'],row['backend'],row['sample_id'])].append(row)
    sample_data=[]
    for (model,backend,sample_id), trials in grouped.items():
        row=trials[0]
        source_ref=row.get('reference_source','').strip()
        english_ref=row.get('reference_english','').strip()
        language=row.get('language','').lower()
        src=modal_output(trials,'source_prediction')
        eng=modal_output(trials,'english_prediction')
        source_wer = None if language.split('-')[0] in WORDLESS_LANGUAGES or not source_ref else word_error_rate(source_ref,src)
        source_cer = char_error_rate(source_ref,src) if source_ref else None
        # If manifest references were not retained, prefer CSV source WER/CER
        # but only for score-able languages. Do NOT fabricate English references.
        if not source_ref and row.get('source_cer',''):
            try:source_cer=float(row['source_cer'])
            except ValueError: pass
        if not source_ref and language.split('-')[0] not in WORDLESS_LANGUAGES and row.get('source_wer',''):
            try:source_wer=float(row['source_wer'])
            except ValueError: pass
        sample_data.append({'model':model,'backend':backend,'sample_id':sample_id,
            'language':language,'trials':len(trials),'reference_source':source_ref,
            'source_prediction':src,'source_wer':source_wer,'source_cer':source_cer,
            'reference_english':english_ref,'english_prediction':eng,
            'sentence_chrf':sacrebleu.sentence_chrf(eng,[english_ref]).score if sacrebleu and english_ref else None})
    results=[]
    for model,backend in ORDER:
        items=[r for r in sample_data if (r['model'],r['backend'])==(model,backend)]
        if not items:continue
        numeric=lambda field:[r[field] for r in items if r[field] is not None]
        src_wer=numeric('source_wer')
        src_cer=numeric('source_cer')
        eng=[r for r in items if r['reference_english']]
        # chrF is more tolerant than BLEU of word order / inflection, but neither
        # can replace human evaluation of meaning-preserving translation.
        corpus_bleu = sacrebleu.corpus_bleu([r['english_prediction'] for r in eng],
              [[r['reference_english'] for r in eng]]).score if sacrebleu and eng else None
        corpus_chrf = sacrebleu.corpus_chrf([r['english_prediction'] for r in eng],
              [[r['reference_english'] for r in eng]]).score if sacrebleu and eng else None
        results.append({'model':model,'backend':backend,'n_unique_samples':len(items),
            'n_source_wer_scored':len(src_wer),'n_source_cer_scored':len(src_cer),
            'n_translation_scored':len(eng),
            'n_non_english_source_scored':sum(bool(r['reference_source']) and r['language'] != 'en' for r in items),
            'mean_source_wer':sum(src_wer)/len(src_wer) if src_wer else None,
            'mean_source_cer':sum(src_cer)/len(src_cer) if src_cer else None,
            'corpus_bleu':corpus_bleu,'corpus_chrf':corpus_chrf})
    return sample_data,results

def write_csv(path,rows):
    if not rows:return
    with Path(path).open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run',required=True,help='One extended/results/<timestamp> folder')
    ap.add_argument('--no-sacrebleu',action='store_true',help='Source CER/WER only')
    a=ap.parse_args()
    run=Path(a.run)
    rows=load_benchmark_files(run)
    if not rows:raise SystemExit(f'No *_trials.csv found under {run}')
    samples,summary=calculate(rows,use_sacrebleu=not a.no_sacrebleu)
    write_csv(run/'accuracy_by_sample.csv',samples)
    write_csv(run/'accuracy_summary.csv',summary)
    print('Saved accuracy reports:',run/'accuracy_summary.csv')
    for s in summary:
        print(f"{s['model']}/{s['backend']}: {s['n_unique_samples']} unique samples; "
              f"source CER={s['mean_source_cer']}; translation chrF={s['corpus_chrf']}")
    if not any(s['n_translation_scored'] for s in summary):
        print('NOTE: No verified English reference translations: no translation quality scores.')
    if max(s['n_unique_samples'] for s in summary)<10:
        print('CAUTION: Fewer than 10 unique clips: results are preliminary.')

if __name__=='__main__':main()
