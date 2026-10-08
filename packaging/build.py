"""Build the program for the system this runs on, so it starts without Python being installed.

    python packaging/build.py              needs uv (https://docs.astral.sh/uv/)

macOS      dist/GT7 Companion by qshi.app
Windows    dist/gt7companion/           the program in a folder

The build has an environment of its own in build/venv-<system>, with a Python that uv
downloads (python-build-standalone). Unlike the Python of Homebrew, which is built for
the macOS it is installed on, that one also runs on older systems; the build checks this
for every file it packs. ``--here`` uses the Python that runs this script instead
(install ``-e ".[app,window,box]" pyinstaller`` into it first).

The result is not signed: macOS and Windows will ask on first start.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"
SYSTEM = {"darwin": "mac", "win32": "windows"}.get(sys.platform, "linux")
# Windows: always the x64 Python, also on ARM computers – the window needs libraries that only exist for x64.
PYTHON = {"mac": "3.13", "windows": "cpython-3.13-windows-x86_64-none"}.get(SYSTEM, "3.13")
MINIMUM_MACOS = "14.0"                   # the oldest macOS the app claims to run on (LSMinimumSystemVersion)
_MACH_O = {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"}


def run(*command: str | Path) -> None:
    print("+", " ".join(str(part) for part in command), flush=True)
    subprocess.run([str(part) for part in command], cwd=ROOT, check=True)


def environment(fresh: bool) -> Path:
    """The build environment; returns its Python."""
    uv = shutil.which("uv")
    if uv is None:
        sys.exit("uv is missing (https://docs.astral.sh/uv/getting-started/installation/); "
                 "or use --here with a Python that has the packages.")
    folder = BUILD / f"venv-{SYSTEM}"
    python = folder / ("Scripts/python.exe" if SYSTEM == "windows" else "bin/python")
    if fresh and folder.exists():
        shutil.rmtree(folder)
    if not python.exists():
        run(uv, "venv", "--python", PYTHON, "--python-preference", "only-managed", folder)
    run(uv, "pip", "install", "--python", python, "-e", f"{ROOT}[app,window,box]", "pyinstaller")
    return python


def is_mach_o(path: Path) -> bool:
    try:
        with path.open("rb") as file:
            return file.read(4) in _MACH_O
    except OSError:
        return False


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def check_macos_files(app: Path, limit: str = MINIMUM_MACOS) -> list[str]:
    """Every program file in the app must run on ``limit`` and must not point outside the system.

    Returns what is wrong, one line per file. Helpers in Contents/Helpers have a floor of their own.
    """
    problems = []
    for path in sorted(app.rglob("*")):
        if path.is_symlink() or not path.is_file() or not is_mach_o(path) or "Helpers" in path.relative_to(app).parts:
            continue
        name = path.relative_to(app).as_posix()
        load = subprocess.run(["otool", "-l", str(path)], capture_output=True, text=True, check=True).stdout.splitlines()
        needs = []
        for number, line in enumerate(load):
            words = line.split()
            if words[:1] == ["minos"]:
                needs.append(words[1])
            elif words[:2] == ["cmd", "LC_VERSION_MIN_MACOSX"]:
                needs.append(load[number + 2].split()[1])
        if not needs:
            problems.append(f"{name}: no minimum system found")
        elif max(map(_version, needs)) > _version(limit):
            problems.append(f"{name}: needs macOS {max(needs, key=_version)}")
        linked = subprocess.run(["otool", "-L", str(path)], capture_output=True, text=True, check=True).stdout
        for line in linked.splitlines()[1:]:
            library = line.split()[0]
            if not library.startswith(("/usr/lib/", "/System/", "@rpath", "@loader_path", "@executable_path")):
                problems.append(f"{name}: loads {library}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--here", action="store_true", help="use the Python that runs this script")
    parser.add_argument("--fresh", action="store_true", help="make the build environment anew")
    args = parser.parse_args(argv)

    python = Path(sys.executable) if args.here else environment(args.fresh)
    run(python, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", DIST,
        "--workpath", BUILD / "pyinstaller", ROOT / "packaging" / "gt7companion.spec")

    if SYSTEM == "mac":
        app = next(DIST.glob("*.app"))
        problems = check_macos_files(app)
        if problems:
            print(f"\nNot fit for macOS {MINIMUM_MACOS}:\n  " + "\n  ".join(problems), file=sys.stderr)
            return 1
        print(f"\n{app.relative_to(ROOT)}: every program file runs on macOS {MINIMUM_MACOS} or newer.")
    else:
        print(f"\n{(DIST / 'gt7companion').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
