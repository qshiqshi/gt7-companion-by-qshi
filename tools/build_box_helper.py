"""Build the helper program that lets the Box run on a Mac alone (native/box-helper).

    python tools/build_box_helper.py [TARGET]

Needs a Mac with Apple silicon and Xcode 27 or newer (or the command line tools of that version).
Compiling wants the macOS 27 SDK: the source uses a few declarations that exist only there, each
inside ``if #available(macOS 27.0, *)``, and the compiler has to find them even though that code is
never reached on an older system. The program that comes out runs on macOS 26 and newer.
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
MINIMUM_SDK = 27                         # the first SDK that has everything main.swift names (Xcode 27)

NEEDS = (f"Building the helper needs Xcode {MINIMUM_SDK} or newer (the macOS {MINIMUM_SDK} SDK): main.swift uses "
         f"declarations that exist only there, inside `if #available(macOS {MINIMUM_SDK}.0, *)`. "
         f"The program it makes runs on macOS {MINIMUM_MACOS} and newer.")


def _sdk_version() -> str:
    """The version of the macOS SDK that the compiler will use, or an empty string when it cannot be read."""
    try:
        done = subprocess.run(["xcrun", "--show-sdk-version"], capture_output=True, text=True)
    except OSError:
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def _sdk_note(sdk: str) -> str:
    """One sentence on the SDK of this Mac, for the message of a failed build."""
    if not sdk:
        return "The SDK of this Mac could not be read (is Xcode installed and selected, see xcode-select?)."
    major = sdk.split(".")[0]
    if major.isdigit() and int(major) < MINIMUM_SDK:
        return f"This Mac has the macOS {sdk} SDK, which is too old."
    return f"This Mac has the macOS {sdk} SDK."


def build(target: Path | None = None) -> Path:
    """Compile the helper; returns where it is. Raises ``RuntimeError`` with what the compiler said."""
    if sys.platform != "darwin":
        raise RuntimeError("the helper of the Box is for macOS only")
    target = target or ROOT / "build" / "gt7c-box"
    target.parent.mkdir(parents=True, exist_ok=True)
    command = ["xcrun", "swiftc", "-O", "-target", f"arm64-apple-macos{MINIMUM_MACOS}", str(SOURCE), "-o", str(target)]
    try:
        done = subprocess.run(command, capture_output=True, text=True)
    except OSError as problem:           # no xcrun at all
        raise RuntimeError(f"the Swift compiler cannot be started ({problem}). {NEEDS}") from None
    if done.returncode:
        raise RuntimeError(f"swiftc failed. {NEEDS} {_sdk_note(_sdk_version())}\n"
                           f"The compiler said:\n{done.stderr.strip() or done.stdout.strip()}")
    return target


if __name__ == "__main__":
    try:
        print(build(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None))
    except RuntimeError as problem:
        sys.exit(str(problem))
