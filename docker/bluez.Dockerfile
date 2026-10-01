# BlueZ for the gateway on Windows. Build context: ./docker
#
# This image is not run as a container. Docker Desktop containers cannot open
# Bluetooth sockets (see docker/compose.windows.yml), but WSL distros can, so
# `make bt-setup` exports this image's filesystem and imports it as its own
# WSL 2 distro (evenG2-bt). `make bt-up` then runs bluez-start in it.
# Nothing is installed into your other WSL distros.
FROM debian:trixie-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends bluez dbus kmod \
 && rm -rf /var/lib/apt/lists/*
# Also serve the system bus on the tmpfs every WSL distro shares; Docker
# Desktop mounts it into the gateway container as /var/run/dbus.
COPY bluez-dbus.conf /etc/dbus-1/system-local.conf
COPY bluez-wsl.conf /etc/wsl.conf
COPY bluez-start.sh /usr/local/bin/bluez-start
# Strip CRLF in case the files were checked out on Windows with autocrlf.
RUN sed -i 's/\r$//' /usr/local/bin/bluez-start /etc/dbus-1/system-local.conf /etc/wsl.conf \
 && chmod +x /usr/local/bin/bluez-start
