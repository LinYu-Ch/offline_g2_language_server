# Capstone Whisper benchmarks and integration tests

This folder is the **team-owned testing code** for the existing `offline_g2_language_server` repository. It does not modify Whisper, its Docker images, the G2 gateway, or model weights.

## Layout

| Location | Purpose |
|---|---|
| `benchmark.py` | Base/Small two-pass `whisper-server` benchmark; produces a CSV for each configuration |
| `env_report.py` | Hardware, software revision, and model SHA-256 record |
| `scripts/run_matrix.ps1` | Backward-compatible shortcut to the maintained extended runner |
| `scripts/smoke_test.ps1` | Check that the local Whisper server transcribes the included JFK WAV |
| `extended/run_extended_matrix.ps1` | **Maintained** benchmark runner: CPU/GPU, timestamped sessions, resource monitoring, accuracy summaries and plots |
| `extended/monitor_run.py` | Sample Docker CPU/RAM and NVIDIA GPU/VRAM while benchmarking |
| `extended/accuracy_report.py` | Score real transcript and translation references (if provided) |
| `extended/plot_extended.py` | Regenerate session graphs from recorded CSV/JSON, without rerunning inference |
| `extended/live_stream_report.py` | Summarize real `whisper-stream` JSONL inference timings |
| `extended/simulate_bridge.py` | Test the real bridge against a mock HTTP gateway (not BLE or physical display) |
| `extended/lens_latency.py` | Score **manually annotated physical G2 lens** timing (hardware required) |
| `extended/human_ratings.py` | Report independently collected human translation ratings |
| `tests/` | **All** automated unit and simulated integration tests |
| `extended/fixtures/` | Sample JSONL and blank worksheets/templates, not real multilingual evaluation data |
| `extended/results/` | Timestamped local outputs, ignored by Git |

The legacy `plot_results.py`, duplicate manifests, temporary `.bak` files and bundled generated results were intentionally left out of this source-only release. Keep your existing results separately; do not delete them.

## Windows quick start

From the **repository root** in PowerShell, with Docker Desktop/WSL2 and GNU Make installed:

```powershell
# Install graphing and translation-metric dependencies
python -m pip install -r .\capstone_tests\requirements.txt

# Run every test from one directory (no GPU or glasses required)
python -m unittest discover -s capstone_tests/tests -v

# Prepare the multilingual Base/Small model files if missing
make model M=base
make model M=small

# Benchmark all four configurations (CPU and NVIDIA CUDA GPU)
powershell -NoProfile -ExecutionPolicy Bypass -File .\capstone_tests\extended\run_extended_matrix.ps1 -Repeats 5

# CPU only or GPU only
powershell -NoProfile -ExecutionPolicy Bypass -File .\capstone_tests\extended\run_extended_matrix.ps1 -CpuOnly -Repeats 5
powershell -NoProfile -ExecutionPolicy Bypass -File .\capstone_tests\extended\run_extended_matrix.ps1 -GpuOnly -Repeats 5
```

`scripts/run_matrix.ps1` still accepts the same `-CpuOnly`, `-GpuOnly`, `-Repeats`, `-Warmups`, `-BeamSize`, and `-Manifest` options but now delegates to `extended/run_extended_matrix.ps1`. It no longer creates the old flat `results/` and `graphs/` directories. One maintained runner avoids two conflicting benchmark workflows.

The runner uses `/health` to wait for the model, and only transient **warm-up** HTTP requests are retried. Measured requests fail visibly rather than being silently discarded.

## Where results go

Every run is stored in its own folder:

```text
capstone_tests/extended/results/YYYYMMDD_HHMMSS/
    environment.json
    manifest_used.csv
    base_cpu/base_cpu_trials.csv
    base_cpu/resource_samples.csv
    base_cpu/resource_summary.json
    base_cpu/benchmark_stdout.log
    base_cpu/benchmark_stderr.log
    ... corresponding folders for other selected configurations ...
    accuracy_by_sample.csv
    accuracy_summary.csv
    performance_summary.csv
    graphs/
```

Regenerate figures **without** running Whisper again:

```powershell
python .\capstone_tests\extended\accuracy_report.py --run .\capstone_tests\extended\results\YOUR_TIMESTAMP
python .\capstone_tests\extended\plot_extended.py --run .\capstone_tests\extended\results\YOUR_TIMESTAMP
```

These generated folders are excluded by `.gitignore` because transcripts, dataset records and human annotations may contain sensitive material. Back up and share approved results intentionally, separately from the source-code pull request.

## Interpreting the metrics correctly

- **HTTP latency** is two sequential server request/response times (audio upload + possible queuing + inference + response). **It is not speech-end-to-lens latency.**
- **HTTP RTF** is the two-pass round-trip seconds divided by audio seconds. Below 1 means faster-than-real-time processing for that test clip, not proof of real-time captions.
- **Docker CPU percentage** can exceed 100% when more than one CPU core is active. Container RAM is not the same as total system RAM.
- **GPU utilization and VRAM** come from *device-wide* `nvidia-smi` snapshots. A short GPU inference often yields only one or two samples; they are not precise per-process peaks. The default plotting routine omits the GPU-utilization chart unless all GPU configurations have at least three GPU samples.
- **WER/CER** require a checked source-language transcript. **BLEU/chrF** require verified English reference translations. With only the included English JFK smoke clip, there is **no multilingual translation-quality result**.
- **End-to-end physical G2 latency** requires audio/video timestamps from actual lens observations; a mock HTTP response is not evidence that the lenses displayed a caption.
- Percentiles from 3–5 repetitions are descriptive, not robust tail-latency estimates. Repeat varied recordings and document hardware and power settings before drawing final conclusions.

## Known test outcome

The bridge integration suite includes `test_known_issue_final_caption_must_flush_on_eof` as an **expected failure**. The current bridge can exit before delivering a rate-limited final caption. Do not remove the test or report it as a fixed bug until the implementation is corrected and the test passes without `@expectedFailure`.

## Advanced evaluations

See [`extended/README.md`](extended/README.md) for multilingual data format, live VAD JSONL analysis, simulated gateway testing, human translation ratings, and physical lens timing annotations.

## Preparing a pull request

1. Run `python -m unittest discover -s capstone_tests/tests -v`.
2. Review `git status` and `git diff --check`; do not stage model weights, unapproved real recordings, personal text, caches or generated results.
3. Stage only source, tests, templates and documentation (`git add capstone_tests`).
4. Mention the expected-failure regression and hardware-latency limitations in the pull-request description.
