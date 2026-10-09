"""Write the layout presets that ship with the program (src/gt7companion/data/layouts).

    python tools/make_presets.py

Three dashboards for a screen of their own (16:9, 16:10, 4:3) and the overlay for a stream
(16:9, transparent). The dashboards are described here in a compact form: each widget with
its place on the stage and how much larger than in the overlay it is shown. Fine-tuning
happens in the editor; whoever likes a result better can paste it back here.
"""
from __future__ import annotations

import json
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "src/gt7companion/data/layouts"

# Size of each widget at scale 1 (stage pixels), z-order.
BASE = {
    "speed": (230, 83, 20), "gear": (105, 130, 20), "rpm-bar": (510, 64, 18), "pedals": (100, 150, 18),
    "laptimes": (270, 110, 15), "fuel": (172, 90, 15), "tyres": (160, 130, 15), "session-stats": (220, 154, 12),
    "alert-area": (900, 110, 50), "status-dot": (210, 42, 5), "livetime": (360, 84, 15), "position": (120, 102, 15),
    "track-map": (270, 240, 20), "g-forces": (240, 220, 20), "input-trace": (470, 190, 20),
    "wheel-state": (280, 300, 20), "powertrain": (260, 142, 20), "driving-aids": (260, 72, 20),
    "car-class": (120, 26, 15), "milk": (190, 240, 20), "radio": (250, 56, 40),
}
ALERTS = {"events": {
    "best_lap": {"player": "css", "className": "anim-bestlap", "duration": 4000},
    "spin": {"player": "css", "className": "anim-spin", "duration": 3000},
    "crash": {"player": "css", "className": "anim-crash", "duration": 2500},
}}
FONT = {"family": "Helvetica Neue", "fallback": "Helvetica, Arial, sans-serif"}


def widget(name: str, x: float, y: float, scale: float = 1.0, *, width: float | None = None,
           height: float | None = None, visible: bool = True) -> dict:
    base_w, base_h, z = BASE[name]
    entry = {"x": x, "y": y, "scale": scale, "visible": visible, "zIndex": z,
             "config": dict(ALERTS) if name == "alert-area" else {},
             "width": base_w if width is None else width, "height": base_h if height is None else height}
    return entry


def box(name: str, entry: dict) -> tuple[float, float, float, float]:
    """Left, top, right, bottom of a widget on the stage."""
    return (entry["x"], entry["y"], entry["x"] + entry["width"] * entry["scale"],
            entry["y"] + entry["height"] * entry["scale"])


def rpm(x: float, y: float, width: float) -> dict:
    """The rev bar is sized by its width; its height follows."""
    return widget("rpm-bar", x, y, width=width, height=round(width * 78.67 / 625.78))


def layout(kind: str, label: dict, size: tuple[int, int], widgets: dict, **more) -> dict:
    hidden = {name: widget(name, 40, 40, visible=False) for name in BASE if name not in widgets}
    return {"version": 1, "kind": kind, "label": label, "canvas": {"width": size[0], "height": size[1]},
            "font": dict(FONT), "widgets": {**widgets, **hidden}, "widgetCornerRadius": 6, **more}


def dashboard_16x9() -> dict:
    return layout("dashboard", {"de": "Dashboard 16:9", "en": "Dashboard 16:9"}, (1920, 1080), {
        # middle: what you read while driving
        "car-class": widget("car-class", 1528, 4, 1.2),      # above the session box: the dot of the steering
                                                             # angle travels along the top of the rev band
        "rpm-bar": rpm(440, 56, 1040),
        "gear": widget("gear", 594, 216, 1.7),
        "speed": widget("speed", 796, 216, 2.3),
        "livetime": widget("livetime", 672, 500, 1.6),
        "laptimes": widget("laptimes", 744, 654, 1.6),
        "alert-area": widget("alert-area", 550, 856, width=820),
        "status-dot": widget("status-dot", 640, 1012),
        "radio": widget("radio", 880, 1004),
        # left: where am I, what does the car do
        "track-map": widget("track-map", 40, 40, 1.45),
        "g-forces": widget("g-forces", 40, 410, 1.45),
        "input-trace": widget("input-trace", 40, 836, 1.05),
        # right: the state of the car
        "session-stats": widget("session-stats", 1528, 40, 1.6),
        "tyres": widget("tyres", 1576, 312, 1.9),
        "fuel": widget("fuel", 1588, 584, 1.7, height=72),
        "pedals": widget("pedals", 1410, 790, 1.6),
        "milk": widget("milk", 1640, 762, 1.25),
    })


def dashboard_16x10() -> dict:
    return layout("dashboard", {"de": "Dashboard 16:10", "en": "Dashboard 16:10"}, (1920, 1200), {
        "car-class": widget("car-class", 1506, 4, 1.2),
        "rpm-bar": rpm(480, 66, 960),
        "gear": widget("gear", 572, 240, 1.8),
        "speed": widget("speed", 786, 240, 2.45),
        "livetime": widget("livetime", 654, 548, 1.7),
        "laptimes": widget("laptimes", 730, 716, 1.7),
        "alert-area": widget("alert-area", 550, 950, width=820),
        "status-dot": widget("status-dot", 640, 1128),
        "radio": widget("radio", 880, 1120),
        "track-map": widget("track-map", 40, 40, 1.55),
        "g-forces": widget("g-forces", 40, 440, 1.55),
        "input-trace": widget("input-trace", 40, 960),
        "session-stats": widget("session-stats", 1506, 40, 1.7),
        "tyres": widget("tyres", 1560, 330, 2.0),
        "fuel": widget("fuel", 1570, 620, 1.8, height=72),
        "pedals": widget("pedals", 1400, 880, 1.7),
        "milk": widget("milk", 1630, 820, 1.4),
    })


def dashboard_4x3() -> dict:
    return layout("dashboard", {"de": "Dashboard 4:3", "en": "Dashboard 4:3"}, (1440, 1080), {
        "car-class": widget("car-class", 1124, 4, 1.2),
        "rpm-bar": rpm(330, 50, 780),
        "gear": widget("gear", 420, 176, 1.5),
        "speed": widget("speed", 598, 176, 1.85),
        "livetime": widget("livetime", 468, 410, 1.4),
        "laptimes": widget("laptimes", 504, 548, 1.6),
        "alert-area": widget("alert-area", 320, 744, width=800),
        "status-dot": widget("status-dot", 515, 1012),
        "radio": widget("radio", 745, 1004),
        "track-map": widget("track-map", 30, 40, 1.05),
        "g-forces": widget("g-forces", 30, 312, 1.1),
        "tyres": widget("tyres", 30, 574, 1.5),
        "input-trace": widget("input-trace", 30, 860),
        "session-stats": widget("session-stats", 1124, 40, 1.3),
        "fuel": widget("fuel", 1152, 262, 1.5, height=72),
        "milk": widget("milk", 1172, 420, 1.25),
        "pedals": widget("pedals", 1010, 860, 1.25),
        "powertrain": widget("powertrain", 1150, 866),
    })


def overlay_16x9() -> dict:
    """The stream overlay as qshi uses it: around the edges, the middle stays free for the game."""
    return layout("overlay", {"de": "Overlay für den Stream 16:9", "en": "Stream overlay 16:9"}, (1920, 1080), {
        "speed": widget("speed", 938, 933, 0.95),
        "gear": widget("gear", 850, 933, 0.65),
        "rpm-bar": widget("rpm-bar", 840, 845, width=510, height=46),
        "pedals": widget("pedals", 286, 882, visible=False),
        "laptimes": widget("laptimes", 40, 35),
        "fuel": widget("fuel", 1178, 938),
        "tyres": widget("tyres", 1380, 905),
        "session-stats": widget("session-stats", 1660, 35),
        "alert-area": widget("alert-area", 450, 155),
        "status-dot": widget("status-dot", 1680, 1005),
        "livetime": widget("livetime", 780, 35),
        "position": widget("position", 40, 35, visible=False),
        "track-map": widget("track-map", 40, 185),
        "g-forces": widget("g-forces", 40, 445),
        "input-trace": widget("input-trace", 340, 850),
        "wheel-state": widget("wheel-state", 40, 720, visible=False),
        "powertrain": widget("powertrain", 340, 695, visible=False),
        "driving-aids": widget("driving-aids", 1080, 742, visible=False),
        "car-class": widget("car-class", 1760, 4),
        "milk": widget("milk", 1690, 546),
        "radio": widget("radio", 835, 280),
    })


PRESETS = {"dashboard-16x9": dashboard_16x9, "dashboard-16x10": dashboard_16x10,
           "dashboard-4x3": dashboard_4x3, "overlay-16x9": overlay_16x9}


def overlaps(entries: dict) -> list[tuple[str, str]]:
    shown = {name: box(name, entry) for name, entry in entries.items() if entry["visible"]}
    names = sorted(shown)
    return [(a, b) for i, a in enumerate(names) for b in names[i + 1:]
            if shown[a][0] < shown[b][2] and shown[b][0] < shown[a][2]
            and shown[a][1] < shown[b][3] and shown[b][1] < shown[a][3]]


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for name, build in PRESETS.items():
        data = build()
        (TARGET / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        size = data["canvas"]
        outside = [n for n, e in data["widgets"].items() if e["visible"]
                   and (box(n, e)[0] < 0 or box(n, e)[1] < 0 or box(n, e)[2] > size["width"] or box(n, e)[3] > size["height"])]
        print(f"{name}: {sum(e['visible'] for e in data['widgets'].values())} widgets"
              f"{', outside the stage: ' + ', '.join(outside) if outside else ''}"
              f"{', overlapping: ' + str(overlaps(data['widgets'])) if overlaps(data['widgets']) else ''}")


if __name__ == "__main__":
    main()
