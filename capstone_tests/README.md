# Whisper model tests

Tests and benchmarks for the capstone speech engine. These tools compare Whisper Base
and Small on CPU and NVIDIA GPU and check the Python caption bridge without needing
G2 glasses. Run commands from the repository root in **Windows PowerShell**.

## Folder layout

- `scripts/` — runnable benchmarks, reporting tools, and the PowerShell launcher.
- `tests/` — unit and simulated HTTP integration tests.
- `fixtures/` — the JFK smoke-test manifest, examples, and blank data templates.
- `results/` — timestamped benchmark sessions (ignored by Git).

## 1. Setup and test

```powershell
python -m pip install -r .\capstone_tests\requirements.txt
python -m unittest discover -s capstone_tests/tests -v
make model M=base
make model M=small
```

The unit suite includes one **expected failure** for the known issue where
`g2_bridge.py` can exit before flushing its final, rate-limited caption.
That behavior belongs to the bridge itself; the test suite does not change it.

To check the HTTP server independently, start `make whisper WHISPER_MODEL=ggml-base.bin`
and run the smoke test in another PowerShell window:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\capstone_tests\scripts\smoke_test.ps1
```

## 2. CPU/GPU benchmarks

```powershell
# All four configurations, five measured runs per recording
powershell -NoProfile -ExecutionPolicy Bypass -File .\capstone_tests\scripts\run_matrix.ps1 -Repeats 5

# Optional: only CPU or only NVIDIA CUDA GPU
powershell -NoProfile -ExecutionPolicy Bypass -File .\capstone_tests\scripts\run_matrix.ps1 -CpuOnly -Repeats 5
powershell -NoProfile -ExecutionPolicy Bypass -File .\capstone_tests\scripts\run_matrix.ps1 -GpuOnly -Repeats 5
```

The script starts the Whisper HTTP server, waits for `/health`, warms it up,
and requests both transcription and English output. Each session is saved under
`capstone_tests/results/YYYYMMDD_HHMMSS/` with raw trials, sampled hardware
usage, metadata, accuracy summaries, and Matplotlib graphs.

**What is measured:** two sequential HTTP round trips, including request
handling and Whisper inference. These figures are **not** speech-end-to-lens
latency. RTF is request time divided by audio duration. The Docker CPU/RAM
and NVIDIA GPU/VRAM readings are periodic snapshots, not precise hardware peaks;
NVIDIA figures are device-wide. A short GPU run may have very few samples.

### Interpreting the JFK dataset

`fixtures/manifest_smoke.csv` points to an 11-second **English** recording in
whisper.cpp. It is useful for testing the setup and comparing throughput.
It does **not** evaluate foreign-language translation accuracy. With only a
few repeats, P95 is also a preliminary descriptive estimate.

## 3. Multilingual recordings and human ratings

Create a local manifest from `fixtures/manifest_multilingual_template.csv`:

```powershell
Copy-Item .\capstone_tests\fixtures\manifest_multilingual_template.csv .\capstone_tests\fixtures\manifest_multilingual.csv
notepad .\capstone_tests\fixtures\manifest_multilingual.csv
```

Required CSV fields: `sample_id,audio_file,language,reference_source,reference_english`.
The audio path is relative to the repository root. Use 16-kHz mono 16-bit PCM
WAV recordings with independently checked source transcripts and English
translations. Empty references must remain empty—not dummy values.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\capstone_tests\scripts\run_matrix.ps1 -Manifest capstone_tests/fixtures/manifest_multilingual.csv -Repeats 5
```

`accuracy_report.py` scores one unique recording per model/backend, instead
of treating repeated requests as independent audio samples. It reports source
WER/CER when applicable and BLEU/chrF only when English references exist.
Languages without ordinary word separators use CER without naive whitespace WER.
Those scores still need human evaluation of meaning and critical errors.

Optional human review: copy `fixtures/human_translation_ratings_template.csv`,
fill it with actual ratings, and run:

```powershell
python .\capstone_tests\scripts\human_ratings.py --ratings .\your_ratings.csv --out-dir .\capstone_tests\results\human_review
```

## 4. Live stream and display-path tests

**Live microphone inference:**

```powershell
make mic-check
make stream GPU=1 STREAM_MODEL=ggml-small.bin STREAM_LANG=es STREAM_OUTPUT=json | Tee-Object -FilePath .\live_small_gpu.jsonl
# Stop with Ctrl+C; then analyze the saved JSONL:
python .\capstone_tests\scripts\live_stream_report.py --jsonl .\live_small_gpu.jsonl --out-dir .\capstone_tests\results\live_small_gpu
```

This measures `whisper-stream` inference time, not VAD hang time or lens delay.

**Simulated G2 gateway:**

```powershell
python .\capstone_tests\scripts\simulate_bridge.py --jsonl .\capstone_tests\fixtures\mock_stream_example.jsonl --out-dir .\capstone_tests\results\mock_example
```

This exercises the actual Python bridge and a local mock HTTP server.
It measures JSONL-injection-to-HTTP-receipt time, **not** microphone/audio
inference, Bluetooth transfer, or physical caption appearance.

**Physical G2 latency (requires glasses):** Record the end of each spoken
utterance and the first visible caption using a shared audio/video clock.
Copy `fixtures/lens_annotations_template.csv`, fill its trial timestamps, then run:

```powershell
python .\capstone_tests\scripts\lens_latency.py --annotations .\your_lens_annotations.csv --out-dir .\capstone_tests\results\physical_g2
```

The resulting median/P95 lens times and 2.5-second reference line are based
on **observed** display appearance, not HTTP acknowledgement. Use enough
independent observations before making tail-latency claims.

## 5. Rebuild graphs from a saved session

```powershell
python .\capstone_tests\scripts\accuracy_report.py --run .\capstone_tests\results\YYYYMMDD_HHMMSS
python .\capstone_tests\scripts\plot_results.py --run .\capstone_tests\results\YYYYMMDD_HHMMSS
```

Existing session CSVs remain compatible; no model inference is needed to
regenerate the figures. Generated results are ignored by Git, so back them up
separately before replacing or resetting a local working folder.
