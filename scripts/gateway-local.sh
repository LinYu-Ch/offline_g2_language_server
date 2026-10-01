#!/bin/sh
# Linux/macOS: run the G2 gateway natively (`make gateway-local`). On Linux it
# uses the host's BlueZ directly; on macOS, CoreBluetooth. Arguments are passed
# to gateway_server.py.
#
# Installs into men-g2-ble-gateway/.venv with the same pinned packages as the
# Docker image (docker/gateway-constraints.txt). Uses uv when available, which
# also provides Python 3.12 (the image's version); otherwise python3 (3.10+).
set -eu

root=$(cd "$(dirname "$0")/.." && pwd)
gw="$root/men-g2-ble-gateway"
venv="$gw/.venv"
py="$venv/bin/python"
# Relative to $root on purpose: uv misreads an absolute -c path that contains
# a space and fails with "Unexpected '['".
req=men-g2-ble-gateway/requirements.txt
pins=docker/gateway-constraints.txt

# The gateway container would hold port 8765 and the same glasses.
if command -v docker >/dev/null 2>&1 \
   && [ -n "$(docker ps -q --filter 'name=^eveng2mount-gateway-1$' 2>/dev/null)" ]; then
    echo "error: the gateway container is running. Stop it first: make down" >&2
    exit 1
fi

if [ ! -x "$py" ]; then
    if command -v uv >/dev/null 2>&1; then
        echo "Creating men-g2-ble-gateway/.venv with uv (Python 3.12)..."
        uv venv --python 3.12 "$venv"
    elif python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
        echo "Creating men-g2-ble-gateway/.venv with python3..."
        python3 -m venv "$venv"
    else
        echo "error: no Python 3.10+ found. Install uv (it provides Python itself):" >&2
        echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
        exit 1
    fi
fi

# Quick no-op when everything is already installed.
cd "$root"
if command -v uv >/dev/null 2>&1; then
    uv pip install --quiet --python "$py" -r "$req" -c "$pins"
else
    "$py" -m pip install --quiet --disable-pip-version-check -r "$req" -c "$pins"
fi

cd "$gw"
exec "$py" gateway_server.py "$@"
