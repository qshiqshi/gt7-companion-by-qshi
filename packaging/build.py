"""Build the program as a folder that runs without Python being installed.

    pip install -e ".[app]" pyinstaller        (add ".[box]" for sound on the loudspeakers)
    python packaging/build.py

The result is in dist/. It is not signed: macOS and Windows will ask on first start
(macOS: right-click → Open). Signing needs a paid developer certificate.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
               "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"),
               str(ROOT / "packaging" / "gt7companion.spec")]
    return subprocess.call(command, cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
