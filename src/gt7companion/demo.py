"""Demo mode: one recorded lap, played in a loop, so the dashboard works without a console.

The recording is a real qualifying lap (Dragon Trail, 1:39.854, packet format A).
It is replayed unchanged except for the lap counter and the lap times: each
pass counts as the next lap, so lap times, the lap counter and the "best lap"
message have something to show.
"""
from __future__ import annotations

from .models import TelemetryFrame
from .paths import DATA

DEMO_FILE = DATA / "demo" / "dragon-trail-lap.gt7r"
DEMO_LAP_MS = 99_854            # lap time the game reported for the recorded lap
_RECORDED_LAP = 3               # lap number during the recording


def demo_laps(frame: TelemetryFrame, passes: int) -> TelemetryFrame:
    """Renumber the lap of ``frame`` for the given pass through the recording."""
    completed = frame.current_lap - _RECORDED_LAP + passes
    frame.current_lap = completed + 1
    frame.best_lap_ms = frame.last_lap_ms = DEMO_LAP_MS if completed > 0 else -1
    return frame
