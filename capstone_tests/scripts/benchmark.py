#!/usr/bin/env python3
"""Benchmark two Whisper HTTP inference passes for Base and Small.

Timing includes the HTTP request and response as well as inference. It does
not measure the live microphone pipeline or text appearing on the G2 lenses.
"""

import argparse
import csv
import datetime as dt
import hashlib
import http.client
import json
from pathlib import Path
import statistics
import time
from urllib.parse import urlparse
import wave

REPO_ROOT = Path(__file__).resolve().parents[2]
WORDLESS_LANGUAGES = {"ja", "zh", "ko", "th", "lo", "my"}

COLUMNS = [
    "timestamp_utc", "model", "backend", "sample_id", "language", "repeat",
    "audio_seconds", "source_seconds", "english_seconds", "total_seconds",
    "rtf", "source_wer", "source_cer", "english_wer", "english_cer",
    "source_prediction", "english_prediction", "reference_source",
    "reference_english", "file_sha256", "beam_size", "endpoint", "metric_note",
]


def normalize_text(text):
    """Lowercase, remove punctuation, and normalize whitespace."""
    text = str(text).lower()
    text = "".join(char if char.isalnum() or char.isspace() else " " for char in text)
    return " ".join(text.split())


def edit_distance(first, second):
    previous = list(range(len(second) + 1))
    for row_number, item in enumerate(first, 1):
        current = [row_number]
        for column_number, other in enumerate(second, 1):
            current.append(min(
                current[-1] + 1,
                previous[column_number] + 1,
                previous[column_number - 1] + (item != other),
            ))
        previous = current
    return previous[-1]


def word_error_rate(reference, prediction):
    reference_words = normalize_text(reference).split()
    if not reference_words:
        return None
    predicted_words = normalize_text(prediction).split()
    return edit_distance(reference_words, predicted_words) / len(reference_words)


def source_wer_for_language(reference, prediction, language):
    # Naive whitespace tokenization is not suitable for these languages.
    if language.lower().split("-")[0] in WORDLESS_LANGUAGES:
        return None
    return word_error_rate(reference, prediction)


def char_error_rate(reference, prediction):
    reference_chars = normalize_text(reference).replace(" ", "")
    if not reference_chars:
        return None
    predicted_chars = normalize_text(prediction).replace(" ", "")
    return edit_distance(reference_chars, predicted_chars) / len(reference_chars)


def weighted_rtf(times_and_durations):
    audio_duration = sum(duration for _, duration in times_and_durations)
    if audio_duration <= 0:
        raise ValueError("audio duration must be positive")
    return sum(elapsed for elapsed, _ in times_and_durations) / audio_duration


def probe_wav(path):
    with wave.open(str(path), "rb") as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
            raise ValueError(f"{path}: expected 16-kHz mono 16-bit PCM WAV")
        if audio.getcomptype() != "NONE":
            raise ValueError(f"{path}: expected uncompressed PCM WAV")
        duration = audio.getnframes() / audio.getframerate()
    if duration <= 0:
        raise ValueError(f"{path}: WAV contains no audio")
    return duration


def multipart_body(wav_bytes, filename, params):
    boundary = "----CapstoneWhisperBenchmark4d52"
    body = bytearray()
    fields = [("file", (filename, wav_bytes, "audio/wav")), *params.items()]

    for key, value in fields:
        body.extend(f"--{boundary}\r\n".encode("ascii"))
        if key == "file":
            safe_filename = Path(filename).name
            body.extend(
                f'Content-Disposition: form-data; name="file"; filename="{safe_filename}"\r\n'
                'Content-Type: audio/wav\r\n\r\n'.encode("utf-8")
            )
            body.extend(wav_bytes)
        else:
            body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n{value}'.encode("utf-8"))
        body.extend(b"\r\n")

    body.extend(f"--{boundary}--\r\n".encode("ascii"))
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def infer(url, wav_bytes, filename, language, translate, beam_size, timeout):
    endpoint = urlparse(url)
    params = {
        "language": language,
        "translate": "true" if translate else "false",
        "beam_size": str(beam_size),
        "response_format": "json",
    }
    body, content_type = multipart_body(wav_bytes, filename, params)
    connection = http.client.HTTPConnection(endpoint.hostname, endpoint.port or 80, timeout=timeout)
    start = time.perf_counter()
    try:
        connection.request(
            "POST", endpoint.path or "/inference", body=body,
            headers={"Content-Type": content_type, "Content-Length": str(len(body))},
        )
        response = connection.getresponse()
        payload = response.read()
        elapsed = time.perf_counter() - start
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}: {payload[:350]!r}")
        result = json.loads(payload)
        if not isinstance(result.get("text"), str):
            raise RuntimeError(f"Unexpected response: {str(result)[:300]}")
        return result["text"].strip(), elapsed
    finally:
        connection.close()


def load_samples(manifest):
    with manifest.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        required = {"sample_id", "audio_file", "language", "reference_source", "reference_english"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError(f"manifest requires columns {sorted(required)}")
        rows = list(reader)

    if not rows:
        raise ValueError("manifest has no recordings")

    samples = []
    seen_ids = set()
    for row in rows:
        sample_id = (row["sample_id"] or "").strip()
        if not sample_id or sample_id in seen_ids:
            raise ValueError(f"Missing or duplicate sample_id: {sample_id!r}")
        seen_ids.add(sample_id)
        if not (row["language"] or "").strip():
            raise ValueError(f"{sample_id}: missing language")
        if not (row["audio_file"] or "").strip():
            raise ValueError(f"{sample_id}: missing audio_file")
        audio_path = (REPO_ROOT / row["audio_file"]).resolve()
        if not audio_path.is_file():
            raise FileNotFoundError(f"{sample_id}: missing {audio_path}")
        samples.append((row, audio_path, probe_wav(audio_path)))
    return samples


def warm_up(url, sample, wav_path, beam_size, timeout):
    wav_bytes = wav_path.read_bytes()
    for attempt in range(1, 4):
        try:
            infer(url, wav_bytes, wav_path.name, sample["language"], False, beam_size, timeout)
            infer(url, wav_bytes, wav_path.name, sample["language"], True, beam_size, timeout)
            return
        except (OSError, http.client.HTTPException) as error:
            if attempt == 3:
                raise RuntimeError(
                    "Whisper warm-up failed after three attempts. "
                    "Check server logs, readiness, and Windows network filters."
                ) from error
            delay = attempt * 2
            print(f"Warm-up connection failed ({type(error).__name__}: {error}); "
                  f"retrying after {delay}s ({attempt}/3)", flush=True)
            time.sleep(delay)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="capstone_tests/fixtures/manifest_smoke.csv")
    parser.add_argument("--model", required=True, choices=["base", "small"])
    parser.add_argument("--backend", required=True, choices=["cpu", "gpu"])
    parser.add_argument("--out", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--url", default="http://127.0.0.1:8080/inference")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    if args.repeats < 1 or args.warmups < 0 or args.beam_size < 1:
        parser.error("invalid repeats/warmups/beam-size")

    manifest = Path(args.manifest)
    if not manifest.is_absolute():
        manifest = REPO_ROOT / manifest
    samples = load_samples(manifest)
    output = Path(args.out)
    if not output.is_absolute():
        output = REPO_ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)

    for sample, wav_path, duration in samples:
        print(f'Loaded {sample["sample_id"]}: {duration:.2f}s, {wav_path.name}')

    print(f"Warmups: {args.warmups}, excluded from recorded metrics", flush=True)
    first_sample, first_path, _ = samples[0]
    for _ in range(args.warmups):
        # Retries are allowed only before measurement. Never omit failed trials.
        warm_up(args.url, first_sample, first_path, args.beam_size, args.timeout)

    measurements = []
    for sample, wav_path, duration in samples:
        wav_bytes = wav_path.read_bytes()
        file_hash = hashlib.sha256(wav_bytes).hexdigest()
        for repeat in range(1, args.repeats + 1):
            source, source_seconds = infer(
                args.url, wav_bytes, wav_path.name, sample["language"],
                False, args.beam_size, args.timeout,
            )
            english, english_seconds = infer(
                args.url, wav_bytes, wav_path.name, sample["language"],
                True, args.beam_size, args.timeout,
            )
            total_seconds = source_seconds + english_seconds
            record = {
                "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "model": args.model,
                "backend": args.backend,
                "sample_id": sample["sample_id"],
                "language": sample["language"],
                "repeat": repeat,
                "audio_seconds": round(duration, 6),
                "source_seconds": round(source_seconds, 6),
                "english_seconds": round(english_seconds, 6),
                "total_seconds": round(total_seconds, 6),
                "rtf": round(total_seconds / duration, 6),
                "source_wer": source_wer_for_language(sample["reference_source"], source, sample["language"]),
                "source_cer": char_error_rate(sample["reference_source"], source),
                "english_wer": word_error_rate(sample["reference_english"], english),
                "english_cer": char_error_rate(sample["reference_english"], english),
                "source_prediction": source,
                "english_prediction": english,
                "reference_source": sample["reference_source"],
                "reference_english": sample["reference_english"],
                "file_sha256": file_hash,
                "beam_size": args.beam_size,
                "endpoint": args.url,
                "metric_note": "two sequential HTTP round-trips; not actual display latency",
            }
            measurements.append(record)
            print(f'{args.model}/{args.backend} {sample["sample_id"]} repeat={repeat}: '
                  f'source={source_seconds:.2f}s translation={english_seconds:.2f}s '
                  f'RTF={record["rtf"]:.2f}', flush=True)

    with output.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(measurements)

    print(f"Wrote {len(measurements)} trials to {output}")
    print(f'Median total HTTP time = {statistics.median(r["total_seconds"] for r in measurements):.3f}s')
    print(f'Weighted HTTP RTF = {weighted_rtf([(r["total_seconds"], r["audio_seconds"]) for r in measurements]):.3f}')


if __name__ == "__main__":
    main()
