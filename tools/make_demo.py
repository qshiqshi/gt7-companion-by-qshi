"""Cut the demo out of a recording: whole laps, without the pauses, with even time stamps from zero.

    python tools/make_demo.py RECORDING.gt7r FIRST_LAP LAST_LAP [TARGET.gt7r] [START]

A recording is what the private predecessor of this program writes while driving: per packet
8 bytes time stamp and the 296 bytes of format A in ``.gt7r``, and next to it in ``.gt7x`` the
72 more bytes of format C under the same time stamp. Kept are the packets whose lap counter
is FIRST_LAP … LAST_LAP, so the demo starts and ends on the finish line and can be looped.
A recording may hold several drives: START is the number of a packet, the drive is the first
one after it that reaches FIRST_LAP, and it ends where the lap counter leaves the range.
Packets of a paused game are left out. The time stamps of a recording say when a packet
arrived, and over Wi-Fi they arrive in bursts; the game sends 60 a second, so the demo gets
even stamps, one sixtieth apart, and plays smoothly.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD, EXTRA = 8 + 296, 8 + 72


def main(source: str, first_lap: str, last_lap: str, target: str | None = None, start: str = "0") -> int:
    recording = Path(source)
    out = Path(target) if target else ROOT / "src" / "gt7companion" / "data" / "demo" / "demo.gt7r"
    raw = recording.read_bytes()
    more = recording.with_suffix(".gt7x").read_bytes()
    extra = {more[at:at + 8]: more[at + 8:at + EXTRA] for at in range(0, len(more) - EXTRA + 1, EXTRA)}
    laps = range(int(first_lap), int(last_lap) + 1)
    packets, extras, began, paused_count = bytearray(), bytearray(), None, 0
    count = len(raw) // RECORD
    for index in range(int(start), count):
        at = index * RECORD
        packet = raw[at + 8:at + RECORD]
        if struct.unpack_from("<h", packet, 0x74)[0] not in laps:
            if began is None:
                continue                                 # the drive has not begun yet
            break                                        # … and here it is over
        if began is None:
            began = index
        if struct.unpack_from("<H", packet, 0x8E)[0] & 0x0002:           # paused: leave out
            paused_count += 1
            continue
        key = struct.pack("<d", (len(packets) // RECORD) / 60)
        packets += key + packet
        if raw[at:at + 8] in extra:
            extras += key + extra[raw[at:at + 8]]
    out.write_bytes(packets)
    out.with_suffix(".gt7x").write_bytes(extras)
    kept = len(packets) // RECORD
    length = struct.unpack_from("<d", packets, len(packets) - RECORD)[0]
    print(f"{out.name}: {kept} packets from number {began} on, {length:.1f} s, {paused_count} paused packets "
          f"left out, {len(extras) // EXTRA} with the bytes of format C")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    sys.exit(main(*sys.argv[1:6]))
