"""Build the helper program that lets the Box run on a Mac alone (native/box-helper).

    python tools/build_box_helper.py [TARGET]

Needs a Mac with Apple silicon and the Xcode command line tools of macOS 26 or newer.
Without TARGET the program goes to build/gt7c-box, where a start from the source finds it
(see src/gt7companion/engineer/helper.py); packaging/build.py puts it into the app.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "native" / "box-helper" / "main.swift"
MINIMUM_MACOS = "26.0"                   # the first system with on-device speech recognition and language model


def build(target: Path | None = None) -> Path:
    """Compile the helper; returns where it is. Raises ``RuntimeError`` with what the compiler said."""
    if sys.platform != "darwin":
        raise RuntimeError("the helper of the Box is for macOS only")
    target = target or ROOT / "build" / "gt7c-box"
    target.parent.mkdir(parents=True, exist_ok=True)
    command = ["xcrun", "swiftc", "-O", "-target", f"arm64-apple-macos{MINIMUM_MACOS}", str(SOURCE), "-o", str(target)]
    done = subprocess.run(command, capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(f"swiftc failed:\n{done.stderr.strip() or done.stdout.strip()}")
    return target


if __name__ == "__main__":
    try:
        print(build(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None))
    except RuntimeError as problem:
        sys.exit(str(problem))
