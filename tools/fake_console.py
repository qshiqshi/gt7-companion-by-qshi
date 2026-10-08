"""A stand-in PlayStation on this computer, to try the live path without a console.

    python tools/fake_console.py [SECONDS]

Waits for the heartbeat of the program, then sends the recorded demo drive as real,
encrypted packets, 60 a second (in a loop, for SECONDS; default 120) – in the packet
format the heartbeat asks for, like the game does.

In the program choose "PlayStation in the home network" and enter 127.0.0.1 as the
address of the console. Only one program can stand in for the console at a time, and a
real console must not be reachable under that address.
"""
from __future__ import annotations

import socket
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gt7companion import telemetry                          # noqa: E402
from gt7companion.demo import DEMO_FILE                     # noqa: E402

HEARTBEAT_PORT = 33739          # where the game listens for heartbeats
RECORD = 8 + 296                # a time stamp and one packet of format A
SIZES = {b"A": 296, b"B": 316, b"C": 368}


def main(seconds: float = 120.0) -> int:
    raw = DEMO_FILE.read_bytes()
    more = telemetry.read_extension(DEMO_FILE)              # the bytes that formats B and C add
    records = [(struct.unpack_from("<d", raw, at)[0], raw[at + 8: at + RECORD] + more.get(raw[at:at + 8], b""))
               for at in range(0, len(raw) - RECORD + 1, RECORD)]
    lap = records[-1][0] - records[0][0] + 1 / 60
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as console:
        console.bind(("127.0.0.1", HEARTBEAT_PORT))
        print("waiting for the program (source: PlayStation, address 127.0.0.1) …", flush=True)
        wanted, program = console.recvfrom(16)
        size = SIZES.get(wanted[:1], 296)
        print(f"heartbeat {wanted[:1].decode(errors='replace')} from {program[0]}:{program[1]}, "
              f"sending packets of {size} bytes for {seconds:.0f} s", flush=True)
        console.setblocking(False)
        began, sent = time.monotonic(), 0
        while time.monotonic() - began < seconds:
            stamp, packet = records[sent % len(records)]
            due = began + (sent // len(records)) * lap + (stamp - records[0][0])
            if due > time.monotonic():
                time.sleep(due - time.monotonic())
            console.sendto(telemetry._encrypt(packet[:size], seed=0x1000 + sent), program)
            sent += 1
            try:
                while True:                                  # later heartbeats may ask for another format
                    size = SIZES.get(console.recvfrom(16)[0][:1], size)
            except OSError:
                pass
    print(f"sent {sent} packets", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 120.0))
