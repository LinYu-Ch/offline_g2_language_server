#!/usr/bin/env python3
"""
g2_bridge.py -- render governor between whisper.cpp JSONL and men-g2-ble-gateway.

Usage:
    ./stream -m models/ggml-large-v3-q5_0.bin -l ja | python g2_bridge.py
    ./stream ... | tee raw.jsonl | python g2_bridge.py --max-cols 32

Reads one JSON object per line on stdin:
    {"id":0,"t":1234,"dur":2.51,"infer_ms":880,"lang":"ja",
     "source":"...","english":"..."}

Owns the display exclusively. Nothing else should POST to the gateway.
"""

import argparse
import collections
import http.client
import json
import sys
import textwrap
import threading
import time
import urllib.parse

# --- tunables (override via CLI) -------------------------------------------
GATEWAY_URL   = "http://127.0.0.1:8765/api/display"
MAX_COLS      = 34      # chars per line -- SET FROM YOUR CALIBRATION RUN
MAX_LINES     = 6       # lines that fit in 288px, minus one for headroom
BYTE_CAP      = 950     # gateway caps in-place text at 1000 BYTES
MIN_INTERVAL  = 0.34    # ~3 Hz; gateway text queue interval is 100ms
KEEPALIVE_S   = 20.0    # re-send identical text to defeat display timeout
IDLE_CLEAR_S  = 45.0    # blank the lenses after this much silence
MAX_LAG_S     = 8.0     # drop captions this far behind the live audio
WINDOW        = 6       # utterances retained in the rolling caption window
POST_TIMEOUT  = 2.0

_inbox = collections.deque()
_lock = threading.Lock()


def reader():
    """Consume stdin on its own thread; the main loop must never block on it."""
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw.startswith("{"):
            # whisper.cpp logs to stderr, but be defensive about stray stdout
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            print(f"[bridge] unparseable: {raw[:80]}", file=sys.stderr, flush=True)
            continue
        with _lock:
            _inbox.append(obj)
    with _lock:
        _inbox.append(None)  # EOF sentinel


def wrap(window, max_cols, max_lines, byte_cap):
    """Newest-last layout. We wrap in Python because device font metrics are
    undocumented -- letting the firmware reflow makes line count unpredictable,
    and line count is what the rolling window depends on."""
    lines = []
    for text in reversed(window):
        w = textwrap.wrap(text, max_cols) or [""]
        if lines and len(lines) + len(w) > max_lines:
            break
        lines = w + lines
        if len(lines) >= max_lines:
            lines = lines[-max_lines:]
            break

    out = "\n".join(lines)
    # Byte cap, not character cap. CJK/Cyrillic are 2-3 bytes per char in UTF-8
    # and will blow the limit long before the screen looks full.
    while len(out.encode("utf-8")) > byte_cap and "\n" in out:
        out = out.split("\n", 1)[1]
    while len(out.encode("utf-8")) > byte_cap:
        out = out[1:]
    return out


class Display:
    """Stdlib-only HTTP client holding one keep-alive connection. urllib would
    open a fresh socket per write -- ~8k sockets into TIME_WAIT over a long
    session. No third-party dependency, so this runs in the gateway's own venv."""

    def __init__(self, url, timeout, token=None):
        p = urllib.parse.urlparse(url)
        self.host = p.hostname or "127.0.0.1"
        self.port = p.port or 8765
        self.path = p.path or "/api/display"
        self.timeout = timeout
        self.token = token
        self.conn = None
        self.shown = None
        self.last_post = 0.0
        self.fail_streak = 0

    def _connect(self):
        if self.conn is None:
            self.conn = http.client.HTTPConnection(
                self.host, self.port, timeout=self.timeout)

    def _drop(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    def push(self, text, force=False):
        """Returns True if the write landed. Never raises -- a dead gateway
        must not take down the pipeline."""
        if text == self.shown and not force:
            return True

        body = json.dumps({"text": text}).encode("utf-8")
        headers = {"Content-Type": "application/json",
                   "Content-Length": str(len(body))}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        # One retry: a keep-alive socket the server has since closed fails on
        # the first write and succeeds immediately after a reconnect.
        for attempt in (0, 1):
            try:
                self._connect()
                self.conn.request("POST", self.path, body=body, headers=headers)
                resp = self.conn.getresponse()
                payload = resp.read()
                if resp.status >= 400:
                    raise RuntimeError(f"HTTP {resp.status}: {payload[:120]!r}")
                self.shown = text
                self.last_post = time.monotonic()
                if self.fail_streak:
                    print(f"[bridge] display recovered after {self.fail_streak} failures",
                          file=sys.stderr, flush=True)
                    self.fail_streak = 0
                return True
            except Exception as e:
                self._drop()
                if attempt == 0:
                    continue
                self.fail_streak += 1
                if self.fail_streak in (1, 5) or self.fail_streak % 50 == 0:
                    print(f"[bridge] display write failed ({self.fail_streak}): {e}",
                          file=sys.stderr, flush=True)
                return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=GATEWAY_URL)
    ap.add_argument("--max-cols", type=int, default=MAX_COLS)
    ap.add_argument("--max-lines", type=int, default=MAX_LINES)
    ap.add_argument("--window", type=int, default=WINDOW)
    ap.add_argument("--max-lag", type=float, default=MAX_LAG_S)
    ap.add_argument("--keepalive", type=float, default=KEEPALIVE_S)
    ap.add_argument("--idle-clear", type=float, default=IDLE_CLEAR_S)
    ap.add_argument("--rate", type=float, default=MIN_INTERVAL,
                    help="minimum seconds between display writes")
    ap.add_argument("--source", action="store_true",
                    help="display the source-language pass instead of English")
    ap.add_argument("--no-lag-drop", action="store_true",
                    help="never drop stale utterances (matches upstream semantics)")
    ap.add_argument("--token", default=None,
                    help="bearer token, if auth is enabled in config/gateway.yaml")
    args = ap.parse_args()

    threading.Thread(target=reader, daemon=True).start()

    disp = Display(args.url, POST_TIMEOUT, token=args.token)
    window = collections.deque(maxlen=args.window)

    wall0 = time.monotonic()       # approximates the audio clock origin
    last_utterance = wall0
    eof = False
    n_shown = n_dropped = 0
    rtf_worst = 0.0

    print("[bridge] running", file=sys.stderr, flush=True)

    while True:
        now = time.monotonic()

        with _lock:
            batch = [_inbox.popleft() for _ in range(len(_inbox))]

        for obj in batch:
            if obj is None:
                eof = True
                continue

            primary = "source" if args.source else "english"
            text = (obj.get(primary) or obj.get("source") or "").strip()
            if not text:
                continue

            # Real-time factor. Sustained >1.0 with an unbounded upstream queue
            # means captions drift arbitrarily far behind and never recover.
            dur = obj.get("dur", 0.0) or 0.0
            if dur > 0:
                rtf = (obj.get("infer_ms", 0) / 1000.0) / dur
                if rtf > rtf_worst:
                    rtf_worst = rtf
                if rtf > 1.0:
                    print(f"[bridge] RTF {rtf:.2f} on utt {obj.get('id')} "
                          f"-- inference slower than realtime",
                          file=sys.stderr, flush=True)

            # Staleness. The upstream queue never drops; for a live HUD a
            # caption that arrives 10s late is worse than no caption.
            audio_end = obj.get("t", 0) / 1000.0 + dur
            lag = (now - wall0) - audio_end
            if not args.no_lag_drop and lag > args.max_lag:
                n_dropped += 1
                print(f"[bridge] dropped utt {obj.get('id')} lag={lag:.1f}s",
                      file=sys.stderr, flush=True)
                continue

            window.append(text)
            last_utterance = now
            n_shown += 1

        target = wrap(list(window), args.max_cols, args.max_lines, BYTE_CAP)

        # 1. Content changed -- write, rate limited.
        if target != disp.shown and (now - disp.last_post) >= args.rate:
            disp.push(target)

        # 2. Idle -- blank the lenses rather than leave stale text in view.
        elif window and (now - last_utterance) > args.idle_clear:
            window.clear()
            disp.push("")

        # 3. Keepalive -- re-send identical content so a display timeout or a
        #    silent reconnect cannot leave the lenses dark.
        elif disp.shown is not None and (now - disp.last_post) > args.keepalive:
            disp.push(disp.shown, force=True)

        # 4. Retry a failed write without waiting for new content.
        elif disp.fail_streak and (now - disp.last_post) >= 1.0:
            disp.push(target, force=True)

        if eof:
            with _lock:
                empty = not _inbox
            if empty:
                break

        time.sleep(0.05)

    print(f"[bridge] done: shown={n_shown} dropped={n_dropped} "
          f"worst_rtf={rtf_worst:.2f}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()