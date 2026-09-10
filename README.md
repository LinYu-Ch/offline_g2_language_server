# evenG2mount

Minimal Docker setup for two independent services:

| Service   | Source                 | Container port | What it is                                    |
|-----------|------------------------|----------------|-----------------------------------------------|
| `whisper` | `whisper.cpp/`         | 8080           | `whisper-server` HTTP transcription API (CPU) |
| `gateway` | `men-g2-ble-gateway/`  | 8765           | Even G2 BLE gateway, headless (HTTP/WS + UI)  |

Neither service depends on the other; start either one alone.

## Setup

1. **Install Docker** (Docker Desktop on Windows/macOS, Docker Engine + Compose v2 on Linux) and make sure the daemon is running.
2. **Install GNU make.** On Windows, `mingw32-make` works: use it wherever this README says `make`, or alias it.
3. **Put a model in `whisper.cpp/models/`.** The folder is mounted read-only into the container, so models are never baked into the image. The default is `ggml-base.en.bin`:

   ```bash
   sh whisper.cpp/models/download-ggml-model.sh base.en
   ```

   On Windows use `whisper.cpp\models\download-ggml-model.cmd base.en`.

4. **(Gateway only)** `men-g2-ble-gateway/config/` is mounted into the container. `gateway.yaml` is created there on first run if it does not exist.

## Operations

| Command                                      | Effect                                                         |
|----------------------------------------------|----------------------------------------------------------------|
| `make whisper`                               | Build and start the whisper.cpp server on `localhost:8080`     |
| `make whisper WHISPER_MODEL=<file>.bin`      | Same, with a different model from `whisper.cpp/models/`        |
| `make gateway`                               | Build and start the gateway on `localhost:8765`                |
| `make logs`                                  | Follow logs of all services                                    |
| `make logs S=whisper`                        | Follow logs of a single service (`whisper` or `gateway`)       |
| `make down`                                  | Stop and remove all containers                                 |

Re-running `make whisper` or `make gateway` rebuilds if sources changed and recreates the container.

### Configuration variables

Pass these on the `make` command line or set them in the environment:

| Variable        | Default            | Used by   |
|-----------------|--------------------|-----------|
| `WHISPER_MODEL` | `ggml-base.en.bin` | `whisper` |
| `WHISPER_PORT`  | `8080`             | `whisper` |
| `GATEWAY_PORT`  | `8765`             | `gateway` |

Example: `make whisper WHISPER_MODEL=ggml-large-v3-turbo-q5_0.bin WHISPER_PORT=9000`.

## Using the services

**Transcribe a file** (input must be WAV; the image ships without ffmpeg):

```bash
curl http://localhost:8080/inference -F file=@whisper.cpp/samples/jfk.wav -F response_format=json
```

**Gateway:**

- Browser UI: http://localhost:8765
- Status: `curl http://localhost:8765/api/status`
- Show text: `curl -X POST http://localhost:8765/api/display -H "Content-Type: application/json" -d "{\"text\":\"hello\"}"`

See `men-g2-ble-gateway/README.md` and `API.md` for the full API.

## Limitations

- **Bluetooth works only on a Linux host.** The gateway reaches BLE through the host's BlueZ daemon, via the mounted `/var/run/dbus` socket. Docker Desktop on Windows and macOS runs containers inside a VM with no Bluetooth access. There the container starts and serves HTTP, but it never finds the glasses. On those platforms, run the gateway natively (`python gateway_server.py`).
- On Linux, if the gateway logs D-Bus permission errors, add `security_opt: [apparmor:unconfined]` to the `gateway` service in `docker-compose.yml`.
- The whisper image is compiled for the build machine's CPU (`GGML_NATIVE`), so build it on the machine that runs it.
- Docker must have more memory available than the size of the model file. Large models can exceed Docker Desktop's default memory limit.
- The FastMCP endpoint and the microphone/`stream` pipeline (`g2_bridge.py`) are not containerized.
