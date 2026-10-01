#!/bin/sh
# Runs in the evenG2-bt WSL distro: starts the system bus and bluetoothd, and
# stays in the foreground until stopped. The wsl.exe session running it is
# what keeps WSL from shutting the distro down, so scripts/bt.ps1 starts it in
# a hidden window (`make bt-up`) and stops it with wsl --terminate.
#
#   bluez-start              log to the terminal
#   bluez-start background   log to /var/log/bluez.log (`make bt-logs`)
#
# The adapter can be attached with usbipd before or after this starts;
# bluetoothd picks it up either way.
set -eu

if [ "${1:-}" = "background" ]; then
    exec >/var/log/bluez.log 2>&1
fi

SHARE=/mnt/wsl/evenG2

stop() {
    trap - INT TERM EXIT
    [ -n "${bt_pid:-}" ] && kill "$bt_pid" 2>/dev/null || true
    [ -f /run/dbus/pid ] && kill "$(cat /run/dbus/pid)" 2>/dev/null || true
    rm -f "$SHARE/system_bus_socket"
    echo "BlueZ stopped."
}
trap stop INT TERM EXIT

# btusb binds the adapter when usbipd attaches it. Loading it up front means
# attach order does not matter.
modprobe btusb 2>/dev/null || echo "warning: could not load btusb" >&2

mkdir -p "$SHARE" /run/dbus
rm -f "$SHARE/system_bus_socket" /run/dbus/system_bus_socket /run/dbus/pid
dbus-daemon --system --fork

/usr/libexec/bluetooth/bluetoothd -n &
bt_pid=$!

if ls /sys/class/bluetooth/hci* >/dev/null 2>&1; then
    sleep 1
    bluetoothctl power on >/dev/null 2>&1 || true
    bluetoothctl show | grep -E '^Controller|Powered:' || true
else
    echo "No adapter attached yet. From Windows: make bt-list, then make bt-attach BUSID=<id>"
fi

echo "BlueZ is running."
wait "$bt_pid"
