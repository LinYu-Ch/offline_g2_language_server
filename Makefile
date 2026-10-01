.PHONY: help model whisper stream captions mic-check gateway gateway-local bt-check bt-setup bt-remove bt-up bt-down bt-logs bt-list bt-attach bt-detach down logs

# Microphone and Bluetooth passthrough are host-specific, so every compose call
# layers docker/compose.<platform>.yml over docker-compose.yml.
ifeq ($(OS),Windows_NT)
PLATFORM := windows
# If make runs recipes through Git Bash, stop it rewriting container paths
# like /usr/local/bin/... into C:/Program Files/Git/... for docker.exe.
export MSYS_NO_PATHCONV := 1
export MSYS2_ARG_CONV_EXCL := *
# wsl.exe prints UTF-16 when its output is piped, unless told otherwise.
export WSL_UTF8 := 1
# BlueZ runs in a WSL distro; start it before the gateway, stop it on `make down`.
BT_PS1  := powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bt.ps1
BT_UP   := bt-up
BT_DOWN := $(BT_PS1) down
else ifeq ($(shell uname -s),Darwin)
PLATFORM := macos
else
PLATFORM := linux
# Run the stream container as the desktop user so PulseAudio/PipeWire accepts it.
export HOST_UID := $(shell id -u)
export HOST_GID := $(shell id -g)
export XDG_RUNTIME_DIR ?= /run/user/$(HOST_UID)
endif

COMPOSE := docker compose -f docker-compose.yml -f docker/compose.$(PLATFORM).yml

# GPU=1: NVIDIA/CUDA build of the whisper services (docker/compose.gpu.yml),
# compiled for the compute capability nvidia-smi reports, e.g. 8.9 -> 89.
GPU ?= 0
ifeq ($(GPU),1)
COMPOSE += -f docker/compose.gpu.yml
ifeq ($(PLATFORM),windows)
GPU_ARCH := $(strip $(shell powershell -NoProfile -ExecutionPolicy Bypass -File scripts/gpu-arch.ps1))
else
GPU_ARCH := $(strip $(shell nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | tr -d . | sort -u | paste -sd';' -))
endif
# No GPU detected: build for the common architectures instead (slower build).
export CUDA_ARCH ?= $(if $(GPU_ARCH),$(GPU_ARCH),75;80;86;89;90;120)
endif

# Variables read by docker-compose.yml; override on the command line.
export WHISPER_MODEL ?= ggml-base.en.bin
export WHISPER_PORT  ?= 8080
export GATEWAY_PORT  ?= 8765
export STREAM_MODEL  ?= ggml-base.en.bin
export STREAM_LANG   ?= en
export STREAM_OUTPUT ?= text
export BRIDGE_ARGS   ?=

# GATEWAY=local: captions go to a gateway running natively on this machine
# (`make gateway-local`) instead of the gateway container.
GATEWAY ?= docker
ifeq ($(GATEWAY),local)
CAPTIONS_NEEDS :=
export GATEWAY_URL ?= http://host.docker.internal:$(GATEWAY_PORT)/api/display
else
CAPTIONS_NEEDS := gateway
endif

ifeq ($(PLATFORM),windows)
GATEWAY_LOCAL := powershell -NoProfile -ExecutionPolicy Bypass -File scripts/gateway-local.ps1
else
GATEWAY_LOCAL := sh scripts/gateway-local.sh
endif

# Windows: the WSL distro that runs BlueZ, built from docker/bluez.Dockerfile.
BT_DISTRO := evenG2-bt
BT_DIR    := $(LOCALAPPDATA)\evenG2mount\$(BT_DISTRO)

# Plain unquoted echo only: recipes may run under cmd.exe or sh.
help:
	@echo Platform: $(PLATFORM)
	@echo   make stream          live microphone transcription in the terminal, Ctrl+C to stop
	@echo   make captions        live transcription shown on the glasses, starts the gateway
	@echo   make mic-check       show the audio route and the microphones the container sees
	@echo   make model M=base.en download a model into whisper.cpp/models
	@echo   make whisper         whisper-server HTTP API on localhost:$(WHISPER_PORT)
	@echo   make gateway         G2 BLE gateway on localhost:$(GATEWAY_PORT), in Docker
	@echo   make gateway-local   same gateway run natively, on the host Bluetooth stack
	@echo   GATEWAY=local        add to captions to use the native gateway
	@echo   make bt-check        check that the gateway container reaches BlueZ and an adapter
	@echo   GPU=1                add to stream, captions or whisper to use an NVIDIA GPU
	@echo   make logs S=svc      follow logs, S is optional
	@echo   make down            stop and remove containers
	@echo   Windows Bluetooth: bt-setup once, then bt-attach BUSID=x-y each session. See README.md.

# Download a model, e.g. make model M=base.en or M=large-v3-turbo-q5_0.
model:
	$(COMPOSE) run --rm --build models $(M) /models

# Build and start the whisper.cpp server on its own.
# Override the model with: make whisper WHISPER_MODEL=ggml-large-v3-turbo-q5_0.bin
whisper:
	$(COMPOSE) up -d --build whisper

# Build the image if needed and transcribe the default microphone live, in the
# foreground. Extra whisper-stream flags go in ARGS, e.g. make stream ARGS="-vth 2.5 -v".
# STREAM_OUTPUT=json prints JSON Lines instead of captions.
stream:
	$(COMPOSE) run --rm --build stream $(ARGS)

# Same, but captions go through g2_bridge.py to the gateway. Starts the gateway
# container first, unless GATEWAY=local (gateway already running natively).
# g2_bridge.py flags go in BRIDGE_ARGS, e.g. make captions BRIDGE_ARGS="--max-cols 32".
captions: $(CAPTIONS_NEEDS)
	$(COMPOSE) run --rm --build stream captions $(ARGS)

mic-check:
	$(COMPOSE) run --rm --build stream check

# Build and start the G2 BLE gateway. On Windows this also starts BlueZ (bt-up).
gateway: $(BT_UP)
	$(COMPOSE) up -d --build gateway

# Run the gateway natively in the foreground, on the host's own Bluetooth stack
# (no usbipd/WSL on Windows). Pair with: make captions GATEWAY=local.
# gateway_server.py flags go in GATEWAY_ARGS, e.g. GATEWAY_ARGS=--no-gui.
gateway-local:
	$(GATEWAY_LOCAL) --port $(GATEWAY_PORT) $(GATEWAY_ARGS)

bt-check:
	$(COMPOSE) run --rm --build --no-deps gateway python /usr/local/bin/bt_check.py

# --- Windows Bluetooth --------------------------------------------------------
# Build the BlueZ image and import it as the WSL distro evenG2-bt (stored in
# %LOCALAPPDATA%\evenG2mount). Re-running replaces the distro.
bt-setup:
	docker build -t eveng2mount/bluez -f docker/bluez.Dockerfile docker
	-docker rm -f eveng2mount-bluez-export
	docker create --name eveng2mount-bluez-export eveng2mount/bluez
	-wsl --unregister $(BT_DISTRO)
	powershell -NoProfile -Command "New-Item -ItemType Directory -Force -Path '$(BT_DIR)' | Out-Null"
	docker export eveng2mount-bluez-export | wsl --import $(BT_DISTRO) "$(BT_DIR)" - --version 2
	docker rm eveng2mount-bluez-export

bt-remove:
	wsl --unregister $(BT_DISTRO)

# List USB devices and their BUSIDs. Look for the Bluetooth adapter.
bt-list:
	usbipd list

# Attach the adapter to WSL. Windows loses this adapter until bt-detach.
# Needs `usbipd bind --busid <BUSID>` once, from an administrator terminal.
bt-attach:
	usbipd attach --wsl --busid $(BUSID)

bt-detach:
	usbipd detach --busid $(BUSID)

# Run BlueZ in the evenG2-bt distro, in a hidden background window.
# `make gateway` and `make captions` do this for you.
bt-up:
	$(BT_PS1) up

bt-down:
	$(BT_PS1) down

bt-logs:
	$(BT_PS1) logs

# Stop and remove all containers (and BlueZ, on Windows).
down:
	$(COMPOSE) down
	$(BT_DOWN)

# Follow logs. Limit to one service with: make logs S=whisper
logs:
	$(COMPOSE) logs -f $(S)
