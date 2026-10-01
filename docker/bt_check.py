"""Check that the gateway container can reach BlueZ and a powered adapter.

Run with `make bt-check`. Exits non-zero, with a hint, at the first broken link:
D-Bus socket -> system bus -> bluetoothd -> adapter -> powered.
"""

import asyncio
import os
import sys

from dbus_fast import BusType, Message, MessageType
from dbus_fast.aio import MessageBus

SOCKET = "/var/run/dbus/system_bus_socket"

HINT = """
  Windows: BlueZ is not running. Run `make bt-up` (or `make gateway`),
           after `make bt-setup` once; check `make bt-logs`.
  Linux:   start BlueZ on the host: `sudo systemctl start bluetooth`.
  macOS:   not supported in Docker; run the gateway natively."""


def fail(msg: str) -> int:
    print(f"FAIL  {msg}{HINT}")
    return 1


async def main() -> int:
    if not os.path.exists(SOCKET):
        return fail(f"no D-Bus socket at {SOCKET}")
    print(f"ok    D-Bus socket {SOCKET}")

    try:
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    except Exception as exc:  # refused, auth rejected, stale socket...
        return fail(f"cannot connect to the system bus: {exc}")
    print("ok    connected to the system bus")

    reply = await bus.call(Message(
        destination="org.bluez",
        path="/",
        interface="org.freedesktop.DBus.ObjectManager",
        member="GetManagedObjects",
    ))
    if reply.message_type == MessageType.ERROR:
        return fail(f"bluetoothd is not answering: {reply.error_name}")
    print("ok    bluetoothd is running")

    adapters = {
        path: ifaces["org.bluez.Adapter1"]
        for path, ifaces in reply.body[0].items()
        if "org.bluez.Adapter1" in ifaces
    }
    if not adapters:
        return fail("BlueZ sees no Bluetooth adapter (on Windows: is it attached with `make bt-attach`?)")

    powered = False
    for path, props in sorted(adapters.items()):
        on = props["Powered"].value
        powered |= on
        print(f"ok    adapter {path} {props['Address'].value} powered={'yes' if on else 'no'}")
    if not powered:
        return fail("no adapter is powered on (try `bluetoothctl power on` where BlueZ runs)")

    print("Bluetooth is ready.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
