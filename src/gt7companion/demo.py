"""Demo mode: a recorded drive, played in a loop, so the dashboard works without a console.

The recording is four real laps of Deep Forest Raceway in a row, in packet format C – so
the surface under each tyre, the steering angle and the class of the car are there, too.
It starts and ends on the finish line at full speed and is replayed unchanged except for
the lap counter and the lap times: every pass counts on, so lap times, the lap counter and
the "best lap" message have something to show – and stop repeating themselves after the
first pass.

The game reads the packets themselves (see ``game.py``), so the same goes into them:
:class:`DemoPackets`. There the packet number counts on from pass to pass as well – for the
game the demo is one drive that never ends.
"""
from __future__ import annotations

import struct

from .models import TelemetryFrame
from .paths import DATA

DEMO_FILE = DATA / "demo" / "deep-forest-4-laps.gt7r"
DEMO_LAPS_MS = (83_543, 81_978, 82_724, 80_538)     # lap times the game reported for the recorded laps
_RECORDED_LAP = 1                                    # lap number of the first recorded lap
_NUMBER, _LAP, _BEST, _LAST = 0x70, 0x74, 0x78, 0x7C   # where a packet keeps its number, the lap and the lap times
_MAX_LAP, _MAX_NUMBER = 0x7FFF, 0x7FFFFFFF           # what fits into those fields


def _laps(recorded_lap: int, passes: int) -> tuple[int, int, int]:
    """Lap number, last lap time and best lap time for a recorded lap in the given pass."""
    count = len(DEMO_LAPS_MS)
    index = max(0, min(count - 1, recorded_lap - _RECORDED_LAP))          # which of the recorded laps
    lap = passes * count + index + 1
    if passes == 0 and index == 0:
        return lap, -1, -1                                                 # nothing driven yet
    last = DEMO_LAPS_MS[index - 1]                                         # index 0: the last lap of the pass before
    return lap, last, min(DEMO_LAPS_MS if passes else DEMO_LAPS_MS[:index])


def demo_laps(frame: TelemetryFrame, passes: int) -> TelemetryFrame:
    """Renumber the lap of ``frame`` and set its lap times for the given pass through the recording."""
    frame.current_lap, frame.last_lap_ms, frame.best_lap_ms = _laps(frame.current_lap, passes)
    return frame


class DemoPackets:
    """What :func:`demo_laps` does to a frame, written into the packet itself.

    One object per run through the demo: it remembers the last packet number it gave out, so
    the first packet of the next pass gets the number after it.
    """

    def __init__(self) -> None:
        self._pass = 0
        self._shift = 0              # added to the recorded packet numbers of this pass
        self._last: int | None = None

    def __call__(self, packet: bytes, passes: int) -> bytes:
        number, recorded_lap = struct.unpack_from("<ih", packet, _NUMBER)
        if passes != self._pass:
            self._pass = passes
            if self._last is not None:
                self._shift = self._last + 1 - number
        self._last = number = (number + self._shift) & _MAX_NUMBER
        lap, last, best = _laps(recorded_lap, passes)
        out = bytearray(packet)
        struct.pack_into("<ih", out, _NUMBER, number, (lap - 1) % _MAX_LAP + 1)
        struct.pack_into("<ii", out, _BEST, best, last)
        return bytes(out)
