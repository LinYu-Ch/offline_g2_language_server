# evenG2mount

Docker setup for live transcription with Even G2 glasses:

| Service   | Source                | Port | What it is                                                         |
|-----------|-----------------------|------|--------------------------------------------------------------------|
| `stream`  | `whisper.cpp/`        | —    | `whisper-stream`: live transcription of your microphone (CPU), plus `g2_bridge.py` for captions on the glasses |
| `whisper` | `whisper.cpp/`        | 8080 | `whisper-server` HTTP transcription API (CPU)                      |
| `gateway` | `men-g2-ble-gateway/` | 8765 | Even G2 BLE gateway, headless (HTTP/WS + UI)                       |
| `models`  | `whisper.cpp/models/` | —    | Model downloader                                                   |

`stream`, `whisper` and `models` share one image. Every program, script and library runs inside Docker, and the gateway's Python packages are pinned (`docker/gateway-constraints.txt`).

## What the host needs

| Need                 | Windows                                    | Linux                         | macOS                     |
|----------------------|--------------------------------------------|-------------------------------|---------------------------|
| Docker               | Docker Desktop, **WSL 2 backend** (default) | Docker Engine + Compose v2    | Docker Desktop            |
| GNU make             | GnuWin32 `make` or `mingw32-make`, from PowerShell or Git Bash | `make`  | `make`                    |
| Microphone           | Nothing extra (WSLg ships with WSL)        | PulseAudio or PipeWire        | PulseAudio (untested, see below) |
| Bluetooth, gateway in Docker | usbipd-win, see [Windows](#windows) | BlueZ (`bluetoothd`)      | Not possible              |
| Bluetooth, `make gateway-local` | uv or Python 3.10+               | uv or Python 3.10+, BlueZ     | uv or Python 3.10+        |

Microphone and Bluetooth access depend on the host OS. `docker-compose.yml` holds the parts that are the same everywhere. The Makefile adds `docker/compose.windows.yml`, `docker/compose.linux.yml` or `docker/compose.macos.yml` on top, depending on the host. **Use `make`, not plain `docker compose`**, so the right override is applied.

## Quick start

```bash
make model M=base.en
```

```bash
make stream
```

The first command downloads the default model into `whisper.cpp/models/`; skip it if the file is already there. The second prints live captions from your microphone and needs no Bluetooth setup. For captions on the glasses, set up Bluetooth (below), then run `make captions`.

The `whisper.cpp/models/` folder is mounted into the containers, so models are never baked into an image. `men-g2-ble-gateway/config/` is mounted into the gateway; if `gateway.yaml` doesn't exist there, it is created on first run.

## Live transcription: `make stream`

This builds the image if needed, connects the container to your default microphone, and prints captions as you speak. Press **Ctrl+C** to stop. Speech that is still queued gets transcribed before the program exits.

```
[listening]
[00:03] And so my fellow Americans, ask not what your country can do for you.
```

The program is the endpointed-VAD rewrite in `whisper.cpp/examples/stream/stream.cpp`. Captions appear after each pause in speech, not word by word. If a caption is in another language and a translation pass runs, the English text appears under it, prefixed with `->`.

| Variable         | Default            | Effect                                         |
|------------------|--------------------|------------------------------------------------|
| `STREAM_MODEL`   | `ggml-base.en.bin` | Model file in `whisper.cpp/models/`            |
| `STREAM_LANG`    | `en`               | Spoken language (`-l`)                         |
| `STREAM_OUTPUT`  | `text`             | `text` for captions, `json` for JSON Lines     |
| `ARGS`           | —                  | Extra `whisper-stream` flags                   |

Examples:

```bash
make stream ARGS="-vth 2.5 -v"
```

```bash
make stream STREAM_MODEL=ggml-large-v3-q5_0.bin STREAM_LANG=ja
```

The first lowers the VAD threshold and logs VAD decisions. The second transcribes Japanese and also translates it into English.

English-only models (`*.en.bin`) skip the translation pass automatically. Multilingual models run two passes, transcription and translation; add `ARGS=-ntr` to skip the translation pass. `whisper-stream -h` lists every flag.

If nothing is transcribed, run `make mic-check`. It shows the audio server the container is connected to and the microphones it can see.

## Captions on the glasses: `make captions`

```bash
make captions
```

This starts the gateway if it isn't running, then runs `whisper-stream` piped into `g2_bridge.py` in the `stream` container. The bridge posts to `http://gateway:8765/api/display` over the compose network, and the terminal shows each JSON line the bridge receives. Ctrl+C drains the queue, sends the last captions, and exits.

`STREAM_*` and `ARGS` work as for `make stream`. `g2_bridge.py` flags go in `BRIDGE_ARGS`, for example:

```bash
make captions BRIDGE_ARGS="--max-cols 32 --source"
```

If the gateway runs natively (`make gateway-local`, below), add `GATEWAY=local`. Captions then go to `http://host.docker.internal:8765` and no gateway container is started:

```bash
make captions GATEWAY=local
```

## Native gateway: `make gateway-local`

The gateway can also run directly on your machine instead of in Docker. It then uses the OS's own Bluetooth stack: Windows Bluetooth, CoreBluetooth on macOS, or BlueZ on Linux. So on Windows it needs **no usbipd, no `bt-setup` and no `evenG2-bt`**, and Windows keeps its Bluetooth.

```bash
make gateway-local
```

In another terminal:

```bash
make captions GATEWAY=local
```

- It runs in the foreground; Ctrl+C stops it. Flags for `gateway_server.py` go in `GATEWAY_ARGS`, e.g. `GATEWAY_ARGS=--no-gui`. Without that flag, the Tk window opens if `gui.enabled` is set in `config/gateway.yaml`.
- On first run it creates `men-g2-ble-gateway/.venv`, using the pinned versions from `docker/gateway-constraints.txt`. Later runs only check that packages are installed.
- **It needs Python.** With [uv](https://docs.astral.sh/uv/) installed (`winget install astral-sh.uv`), uv provides Python 3.12, the same version as the image, so no system Python is needed. Without uv, any working Python 3.10+ on the PATH is used.
- It refuses to start while the gateway container is running, because both would hold port 8765 and compete for the glasses. Run `make down` first. On Windows, also run `make bt-detach BUSID=…` if the adapter is attached to WSL.

The native gateway is the one part of the project that runs outside Docker, so its Python environment depends on your machine.

## NVIDIA GPU: `GPU=1`

Add `GPU=1` to `make stream`, `make captions` or `make whisper` to run whisper on an NVIDIA GPU:

```bash
make stream GPU=1 STREAM_MODEL=ggml-large-v3-q5_0.bin STREAM_LANG=ja
```

This builds a second image, `eveng2mount/whisper-cuda`, from NVIDIA's CUDA 13 images, and requests the GPU for the container (`docker/compose.gpu.yml`). The CPU image is untouched, and leaving out `GPU=1` uses it as before. To make GPU the default for a shell session, set `GPU=1` in the environment (PowerShell: `$env:GPU=1`).

- **Requirements:**
  - An NVIDIA driver that supports CUDA 13 (R580 or newer).
  - **Windows:** Docker Desktop with the WSL 2 backend, which has GPU support built in.
  - **Linux:** `nvidia-container-toolkit`.
  - macOS and non-NVIDIA GPUs aren't supported; use the CPU image.
- **Build:** the image is compiled for the compute capability `nvidia-smi` reports, for example `89` for an RTX 40-series card. That keeps the CUDA build as short as possible. To build for other GPUs, set the list yourself, e.g. `CUDA_ARCH="86;89"`. If no GPU is detected, it builds for the common architectures, which takes much longer.
- **Size:** the first build downloads several GB of CUDA images and compiles CUDA kernels. Later builds reuse the cache.

## How the microphone reaches the container

`whisper-stream` captures through SDL2 → PulseAudio, and each platform supplies a PulseAudio server:

- **Windows:** WSLg. WSLg runs a PulseAudio server that exposes the Windows default recording device as `RDPSource`. Docker Desktop shares it at `/run/desktop/mnt/host/wslg`. To change the microphone, change the Windows default recording device.
  - Windows must let desktop apps use the microphone: *Settings → Privacy & security → Microphone → Let desktop apps access your microphone*.
  - WSLg starts with WSL. If `mic-check` reports a missing socket, run `wsl -- true` once.
- **Linux:** your user's PulseAudio or PipeWire socket (`$XDG_RUNTIME_DIR/pulse/native`). The container runs with your UID, which the server accepts without a cookie. With PipeWire, `pipewire-pulse` must be running.
- **macOS:** Docker can't reach the Mac's audio hardware directly, so PulseAudio has to run on the Mac. See `docker/compose.macos.yml` for the setup. This route is untested.

## Bluetooth for the gateway

The gateway container never touches the radio itself. Its BLE library, `bleak`, talks over D-Bus to a BlueZ daemon whose socket is mounted at `/var/run/dbus`. Run `make bt-check` to test every link in that chain: socket, bus, `bluetoothd`, adapter, powered.

### Linux

```bash
sudo systemctl start bluetooth
make gateway
```

The container uses the host's BlueZ.

### Windows

The simplest option is to skip this section and run the gateway natively with `make gateway-local` (above). The rest of this section is for running the gateway **in Docker**.

Docker Desktop containers **cannot** use Bluetooth directly, even with `network_mode: host` or `--privileged`. The Linux kernel only allows Bluetooth sockets in the VM's initial network namespace, and Docker Desktop's engine runs in a different one.

A WSL distro does run in that namespace. So:
- `make bt-setup` builds BlueZ from `docker/bluez.Dockerfile` and imports it as a small, dedicated WSL distro, `evenG2-bt`, stored in `%LOCALAPPDATA%\evenG2mount`. Your other WSL distros are not changed.
- usbipd-win hands the USB Bluetooth adapter to WSL.
- The distro's D-Bus also listens in `/mnt/wsl`, which all WSL distros share, and Docker Desktop mounts that into the gateway container.

**One-time setup:**

1. Install usbipd-win from PowerShell, then open a new terminal:
   ```bash
   winget install usbipd
   ```
2. Build and import the BlueZ distro. Re-running it rebuilds the distro, and `make bt-remove` deletes it.
   ```bash
   make bt-setup
   ```
3. Find your Bluetooth adapter's BUSID, for example `2-3`:
   ```bash
   make bt-list
   ```
4. In an **administrator** terminal, share the adapter:
   ```bash
   usbipd bind --busid 2-3
   ```

**Each session** (after a reboot or `wsl --shutdown`):

1. Hand the adapter to WSL:
   ```bash
   make bt-attach BUSID=2-3
   ```
   > ⚠️ While the adapter is attached, **Windows has no Bluetooth**: paired headphones, mice and so on disconnect.
2. Start the gateway, or `make captions`, which starts it:
   ```bash
   make gateway
   ```

`make gateway` and `make captions` first start BlueZ in the `evenG2-bt` distro as a hidden background process (`make bt-up`), unless it's already running. No terminal needs to stay open. The steps can go in either order: BlueZ picks the adapter up whenever it's attached. `make bt-check` tests the whole chain, and `make bt-logs` shows BlueZ's log.

**When you're done:** `make down` stops the containers and BlueZ. Then give the adapter back to Windows:

```bash
make bt-detach BUSID=2-3
```

BlueZ stays attached to a hidden `wsl.exe` process because WSL shuts a distro down when no session is attached to it. `scripts/bt.ps1` starts and stops that process.

The adapter must be a USB device. Most internal laptop adapters are, including Intel AX-series cards. Once BlueZ owns the adapter, pair the glasses through the gateway UI as usual.

### macOS

Bluetooth is not available to containers on macOS. Use `make gateway-local` and `make captions GATEWAY=local`.

## All commands

| Command                                  | Effect                                                        |
|------------------------------------------|---------------------------------------------------------------|
| `make help`                              | List commands and show the detected platform                  |
| `make model M=<name>`                    | Download `ggml-<name>.bin`, e.g. `base.en`, `large-v3-turbo-q5_0` |
| `make stream`                            | Live microphone transcription in the terminal                 |
| `make captions`                          | Live transcription shown on the glasses (starts the gateway)  |
| `make mic-check`                         | Show the container's audio server and microphones             |
| `make whisper`                           | Start `whisper-server` on `localhost:8080`                    |
| `make whisper WHISPER_MODEL=<file>.bin`  | Same, with a different model from `whisper.cpp/models/`       |
| `make gateway`                           | Start the gateway on `localhost:8765`, in Docker              |
| `make gateway-local`                     | Run the gateway natively, on the host's Bluetooth (foreground) |
| `make captions GATEWAY=local`            | Captions to the native gateway                                |
| `make bt-check`                          | Check the gateway container's path to BlueZ and an adapter    |
| `make bt-setup` / `bt-remove`            | Windows: create or delete the `evenG2-bt` BlueZ distro        |
| `make bt-up` / `bt-down` / `bt-logs`     | Windows: start, stop, or show the log of background BlueZ (`gateway`, `captions` and `down` do this for you) |
| `make bt-list` / `bt-attach BUSID=` / `bt-detach BUSID=` | Windows: move the USB adapter between Windows and WSL |
| `make logs` / `make logs S=gateway`      | Follow logs of all services, or of one                        |
| `make down`                              | Stop and remove all containers, and BlueZ on Windows          |

`make whisper` and `make gateway` rebuild the image if its sources changed, and recreate the container only if something changed.

Other variables: `GPU=1` (NVIDIA build, see above), `WHISPER_PORT` (default `8080`) and `GATEWAY_PORT` (default `8765`).

## Using the services

**Transcribe a file.** The input must be WAV, because the image ships without ffmpeg:

```bash
curl http://localhost:8080/inference -F file=@whisper.cpp/samples/jfk.wav -F response_format=json
```

**Gateway:**

- Browser UI: http://localhost:8765
- Status: `curl http://localhost:8765/api/status`
- Show text: `curl -X POST http://localhost:8765/api/display -H "Content-Type: application/json" -d "{\"text\":\"hello\"}"`

From another container on the compose network, the gateway is `http://gateway:8765`, not `127.0.0.1`. See `men-g2-ble-gateway/README.md` and `API.md` for the full API.

## Limitations

- The whisper images are compiled for the build machine's CPU (`GGML_NATIVE`) and, with `GPU=1`, its GPU. Build them on the machine that runs them.
- Docker must have more memory available than the size of the model file. Large models can exceed Docker Desktop's default memory limit.
- On CPU, large models with two passes and beam size 5 can fall behind real time. Captions then arrive late, but no audio is dropped. For live use on CPU, prefer `base.en`, `small`, or `ARGS="-bs 1"`; with an NVIDIA GPU, use `GPU=1`.
- The FastMCP endpoint and the LC3 decoder for the glasses' own microphone (`example_pcm_record.py`) are not containerized.
