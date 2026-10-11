"""Build the Opus library for the Mac app, for macOS 14 and newer.

    python tools/build_opus.py            → build/libopus.0.dylib (packaging/gt7companion.spec packs it)

The Box in the headset (a Discord voice channel) needs Opus. Homebrew's copy is built for the
macOS it was installed on, which is newer than what the app promises (macOS 14); so the library
is built here from the official source, with that floor. Needs the command line tools of Xcode
(clang, make). Takes about a minute.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
VERSION = "1.5.2"
ARCHIVE = f"opus-{VERSION}.tar.gz"
URL = f"https://downloads.xiph.org/releases/opus/{ARCHIVE}"
SUMS = "https://downloads.xiph.org/releases/opus/SHA256SUMS.txt"
FLOOR = "14.0"


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:       # noqa: S310 - fixed https addresses
        return response.read()


def expected_sha256(given: str | None) -> str:
    if given:
        return given.lower()
    for line in fetch(SUMS).decode("utf-8", "replace").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == ARCHIVE:
            return parts[0].lower()
    sys.exit(f"{ARCHIVE} is not in {SUMS}; give --sha256")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--sha256", help="checksum of the source archive (default: the list on the Opus site)")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    args = parser.parse_args(argv)
    if sys.platform != "darwin":
        sys.exit("only needed on a Mac: on Windows discord.py brings the library")
    archive = fetch(URL)
    digest = hashlib.sha256(archive).hexdigest()
    wanted = expected_sha256(args.sha256)
    if digest != wanted:
        sys.exit(f"checksum of {ARCHIVE} is {digest}, expected {wanted}")
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        path = folder / ARCHIVE
        path.write_bytes(archive)
        with tarfile.open(path) as tar:
            tar.extractall(folder, filter="data")
        source = folder / f"opus-{VERSION}"
        prefix = folder / "prefix"
        environment = {**os.environ, "CFLAGS": f"-O2 -mmacosx-version-min={FLOOR}",
                       "LDFLAGS": f"-mmacosx-version-min={FLOOR}", "MACOSX_DEPLOYMENT_TARGET": FLOOR}
        subprocess.run(["./configure", f"--prefix={prefix}", "--disable-static", "--enable-shared",
                        "--disable-extra-programs", "--disable-doc"], cwd=source, env=environment, check=True)
        subprocess.run(["make", f"-j{args.jobs}"], cwd=source, env=environment, check=True)
        subprocess.run(["make", "install"], cwd=source, env=environment, check=True)
        built = prefix / "lib" / "libopus.0.dylib"
        BUILD.mkdir(exist_ok=True)
        target = BUILD / "libopus.0.dylib"
        shutil.copy2(built, target)
    # Loaded by its full path (discord.opus.load_opus), so the install name only has to be self-contained.
    subprocess.run(["install_name_tool", "-id", "@rpath/libopus.0.dylib", str(target)], check=True)
    subprocess.run(["codesign", "--force", "--sign", "-", str(target)], check=True)
    out = subprocess.run(["otool", "-l", str(target)], capture_output=True, text=True, check=True).stdout
    minos = [line.split()[1] for line in out.splitlines() if line.strip().startswith("minos")]
    print(f"{target.relative_to(ROOT)}: {target.stat().st_size} bytes, minimum macOS {', '.join(minos) or '?'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
