#!/bin/sh
# Entrypoint of the `stream` service: live microphone transcription.
#
#   stream-entrypoint [whisper-stream args...]           captions in the terminal
#   stream-entrypoint captions [whisper-stream args...]  captions on the glasses
#   stream-entrypoint check                              show the audio route and mics
#
# Settings come from the environment (see docker-compose.yml):
#   STREAM_MODEL   model file in /models, or an absolute path
#   STREAM_LANG    source language passed to -l
#   STREAM_OUTPUT  "text" for readable captions, "json" for JSON Lines
#   STREAM_THREADS inference threads (default: all cores the container sees)
#   STREAM_GPU     1 in the CUDA image (docker/compose.gpu.yml); 0 adds -ng
#   GATEWAY_URL    display endpoint g2_bridge.py posts to (captions mode)
#   BRIDGE_ARGS    extra g2_bridge.py flags (captions mode)
set -eu

die() {
    echo "error: $*" >&2
    exit 1
}

# Fail early with a useful message instead of SDL's "couldn't open an audio device".
check_audio() {
    case "${PULSE_SERVER:-}" in
        unix:*)
            sock="${PULSE_SERVER#unix:}"
            [ -S "$sock" ] || die "no PulseAudio socket at $sock.
  Windows: Docker Desktop must use the WSL 2 backend, and WSLg must be running
           (run 'wsl -- true' once to start it).
  Linux:   PulseAudio or PipeWire (pipewire-pulse) must be running for your user."
            ;;
        "")
            die "PULSE_SERVER is not set; start the container with 'make stream' so the
  platform audio override (docker/compose.<platform>.yml) is applied."
            ;;
    esac
    pactl info >/dev/null 2>&1 || die "cannot talk to the audio server at $PULSE_SERVER (pactl info failed)."
}

mode=terminal
case "${1:-}" in
    check)
        check_audio
        pactl info | grep -E '^(Server String|Server Name|Default Source):'
        echo "Capture sources:"
        pactl list short sources | grep -v '\.monitor' | sed 's/^/  /'
        exit 0
        ;;
    captions)
        mode=captions
        shift
        ;;
esac

check_audio

model="${STREAM_MODEL:-ggml-base.en.bin}"
case "$model" in
    /*) ;;
    *) model="/models/$model" ;;
esac
if [ ! -f "$model" ]; then
    echo "error: model not found: $model" >&2
    echo "Models available in whisper.cpp/models/:" >&2
    ls /models/*.bin 2>/dev/null | grep -v 'for-tests-' | sed 's|^/models/|  |' >&2 || true
    echo "Download one with: make model M=base.en" >&2
    exit 1
fi

set -- -m "$model" -l "${STREAM_LANG:-en}" -t "${STREAM_THREADS:-$(nproc)}" "$@"
# CPU image: skip the GPU probe. STREAM_GPU=1 comes from docker/compose.gpu.yml.
[ "${STREAM_GPU:-0}" = "1" ] || set -- -ng "$@"

if [ "$mode" = terminal ]; then
    [ "${STREAM_OUTPUT:-text}" = "text" ] && set -- "$@" -txt
    # exec: whisper-stream gets Ctrl+C directly, and drains queued speech before exiting.
    exec whisper-stream "$@"
fi

# Captions: whisper-stream | g2_bridge.py -> gateway. Ctrl+C (or docker stop,
# forwarded to the whole process group by tini) must stop only whisper-stream:
# it drains its queue and exits, the pipe closes, and the bridge posts the
# last captions and exits on EOF. So the shell traps (a handler, which children
# do not inherit) and the bridge side ignores (which they do).
: "${GATEWAY_URL:=http://gateway:8765/api/display}"
trap 'true' INT TERM
echo "Captions -> ${GATEWAY_URL}. JSON lines below are what the bridge receives." >&2
whisper-stream "$@" | (
    trap '' INT TERM
    tee /dev/stderr | python3 /usr/local/bin/g2_bridge.py --url "$GATEWAY_URL" ${BRIDGE_ARGS:-}
)
