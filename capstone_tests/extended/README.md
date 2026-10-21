# Advanced evaluation workflows

The quick start and complete file inventory live in [`../README.md`](../README.md). All commands below run from the **repository root** in Windows PowerShell. This directory contains optional extended measurements, not additional required source installations.

## 1. Resource/performance matrix

```powershell
python -m pip install -r .\capstone_tests\requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\capstone_tests\extended\run_extended_matrix.ps1 -Repeats 5
```

Optional: `-CpuOnly`, `-GpuOnly`, `-Warmups 1`, `-BeamSize 5`, `-Manifest path/to/manifest.csv`.

Each run creates `capstone_tests/extended/results/YYYYMMDD_HHMMSS/`, saving raw per-trial CSVs, Docker/NVIDIA resource samples, summaries and graphs. The runner waits for the inference server's `/health` endpoint after model initialization. No actual Bluetooth or G2 hardware is used. Do not merge independent sessions with different conditions without documenting those differences.

`monitor_run.py` runs `docker stats --no-stream` and `nvidia-smi` while the benchmark is active. These snapshots can **miss memory/utilization spikes** during very short GPU inference. Results are device-wide for the NVIDIA card and container-scoped for Docker CPU/RAM. Longer, repeated workloads are required for confident peak-usage conclusions.

## 2. Foreign-language transcription and English translation

The included `fixtures/manifest_multilingual_TEMPLATE.csv` contains **only column headers**. Create your own file and add genuine checked recordings and reference translations:

```powershell
Copy-Item .\capstone_tests\extended\fixtures\manifest_multilingual_TEMPLATE.csv .\capstone_tests\extended\fixtures\manifest_multilingual.csv
notepad .\capstone_tests\extended\fixtures\manifest_multilingual.csv
```

Required fields:

```csv
sample_id,audio_file,language,reference_source,reference_english
```

Use paths relative to the repository root, e.g. `capstone_tests/fixtures/recordings/es01.wav`. Recordings must be 16-kHz, mono, uncompressed 16-bit PCM WAV. `reference_source` and `reference_english` should be independently checked. Leave missing references truly empty; don't enter placeholder text, and don't claim missing accuracy measures are 0%.

Run the matrix with your manifest:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\capstone_tests\extended\run_extended_matrix.ps1 -Manifest capstone_tests/extended/fixtures/manifest_multilingual.csv -Repeats 5
```

The benchmark uses the same recording for each model and backend, runs independent source-transcription and speech-to-English requests, and stores predictions and verified references in each trial CSV. `accuracy_report.py` scores **one unique clip** per model/backend, rather than treating repeated inferences as independent samples. It omits word-level error estimates for certain languages without ordinary whitespace-delimited words and computes CER when source text is available. Corpus BLEU/chrF are calculated only when English reference translations exist. Neither metric replaces human review of whether meaning was preserved.

Human-rating template: `fixtures/human_translation_ratings_TEMPLATE.csv`. Create a local, blinded review sheet, then:

```powershell
python .\capstone_tests\extended\human_ratings.py --ratings .\your_ratings.csv --out-dir .\capstone_tests\extended\results\human_review
```

## 3. Live speech/VAD inference (without glasses)

To test the **actual microphone-stream** inference timing rather than the HTTP server:

```powershell
make mic-check
make stream GPU=1 STREAM_MODEL=ggml-small.bin STREAM_LANG=es STREAM_OUTPUT=json | Tee-Object -FilePath .\live_small_gpu.jsonl
```

Stop with Ctrl+C, then:

```powershell
python .\capstone_tests\extended\live_stream_report.py --jsonl .\live_small_gpu.jsonl --out-dir .\capstone_tests\extended\results\live_small_gpu
```

This measures utterance `infer_ms` from C++, **not** VAD endpointing, inference queue age, BLE transport or physical lens rendering. For matched comparisons, use the same spoken phrases and record ambient-noise/microphone conditions.

## 4. Gateway simulation (no real hardware)

```powershell
python .\capstone_tests\extended\simulate_bridge.py --jsonl .\capstone_tests\extended\fixtures\mock_stream_example.jsonl --out-dir .\capstone_tests\extended\results\mock_example
```

The simulator feeds JSONL output into the repository's actual `whisper.cpp/g2_bridge.py`. It measures the interval from feeding a finished result to the simulated HTTP gateway receiving the request. It **does not** exercise Whisper audio inference, real BLE delivery or physical captions. The bridge has a documented expected-failure shutdown regression in `tests/test_bridge_integration.py`.

## 5. Physical G2 display-latency annotation

Only perform this with a real pair of glasses and a synchronized audio/video recording that shows the actual rendered caption.

1. Start a native G2 gateway, then the corresponding live captions configuration (`make gateway-local` and `make captions GATEWAY=local GPU=1 STREAM_MODEL=ggml-small.bin STREAM_LANG=es`).
2. For each utterance, note the **end of speech** and the **first clearly visible caption**, using timestamps on the *same recording clock*.
3. Copy `fixtures/lens_annotations_TEMPLATE.csv` to a local sheet and complete `trial_id,model,backend,language,audio_end_s,lens_visible_s,notes`.
4. Run:

```powershell
python .\capstone_tests\extended\lens_latency.py --annotations .\your_lens_annotations.csv --out-dir .\capstone_tests\extended\results\physical_g2
```

The script produces individual latency records and a median/P95 display-latency graph with the 2.5-second target. Percentiles from very few observations should not be presented as robust estimates of tail behavior. HTTP acceptance is **not** proof that pixels appeared on the lenses.

## 6. Graph regeneration

For an existing timestamped run, no model execution is needed:

```powershell
python .\capstone_tests\extended\accuracy_report.py --run .\capstone_tests\extended\results\YOUR_TIMESTAMP
python .\capstone_tests\extended\plot_extended.py --run .\capstone_tests\extended\results\YOUR_TIMESTAMP
```

Generated outputs are intentionally excluded from Git; keep a separate approved archival copy before resetting or deleting local folders. The midterm JFK smoke-test results demonstrate **server throughput only**, not multilingual translation accuracy or physical display performance.
