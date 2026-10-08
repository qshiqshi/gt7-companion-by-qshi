"""Demo mode: a recorded drive, played in a loop, so the dashboard works without a console.

The recording is four real laps of Deep Forest Raceway in a row, in packet format C – so
the surface under each tyre, the steering angle and the class of the car are there, too.
It starts and ends on the finish line at full speed and is replayed unchanged except for
the lap counter and the lap times: every pass counts on, so lap times, the lap counter and
the "best lap" message have something to show – and stop repeating themselves after the
first pass.
"""
from __future__ import annotations

from .models import TelemetryFrame
from .paths import DATA

DEMO_FILE = DATA / "demo" / "deep-forest-4-laps.gt7r"
DEMO_LAPS_MS = (83_543, 81_978, 82_724, 80_538)     # lap times the game reported for the recorded laps
_RECORDED_LAP = 1                                    # lap number of the first recorded lap


def demo_laps(frame: TelemetryFrame, passes: int) -> TelemetryFrame:
    """Renumber the lap of ``frame`` and set its lap times for the given pass through the recording."""
    count = len(DEMO_LAPS_MS)
    index = max(0, min(count - 1, frame.current_lap - _RECORDED_LAP))     # which of the recorded laps
    frame.current_lap = passes * count + index + 1
    if passes == 0 and index == 0:
        frame.last_lap_ms = frame.best_lap_ms = -1                         # nothing driven yet
    else:
        frame.last_lap_ms = DEMO_LAPS_MS[index - 1]                        # index 0: the last lap of the pass before
        frame.best_lap_ms = min(DEMO_LAPS_MS if passes else DEMO_LAPS_MS[:index])
    return frame
