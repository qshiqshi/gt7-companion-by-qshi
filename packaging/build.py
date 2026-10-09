"""Build the program for the system this runs on, so it starts without Python being installed.

    python packaging/build.py              needs uv (https://docs.astral.sh/uv/)

macOS      dist/GT7 Companion by qshi.app
Windows    dist/gt7companion/           the program in a folder, and the same as
           dist/GT7-Companion-by-qshi-windows-x64.zip to pass on

The build has an environment of its own in build/venv-<system>, with a Python that uv
downloads (python-build-standalone). Unlike the Python of Homebrew, which is built for
the macOS it is installed on, that one also runs on older systems; the build checks this
for every file it packs. ``--here`` uses the Python that runs this script instead
(install ``-e ".[app,window,box]" pyinstaller`` into it first).

Without more the result is not signed: macOS and Windows will ask on first start.
For a Mac app that others can simply open (needs a paid Apple developer account):

    python packaging/build.py --sign "Developer ID Application: …" --notarize PROFILE --dmg

``--sign`` signs every program file with the hardened runtime (default: $GT7C_SIGN_IDENTITY),
``--notarize`` has Apple check the result and attaches the ticket (PROFILE is a keychain
profile made with ``xcrun notarytool store-credentials``), ``--dmg`` packs the app into
dist/GT7-Companion-by-qshi-mac-arm64.dmg.
"""
from __future__ import annotations

import argparse
import json
import os
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
PRODUCT = "GT7 Companion by qshi"        # name of the app and the disk image, as in gt7companion.launcher
DISK_IMAGE = "GT7-Companion-by-qshi-mac-arm64.dmg"     # no spaces: the name survives a download link
WINDOWS_ZIP = "GT7-Companion-by-qshi-windows-x64.zip"
BOX_HELPER = "gt7c-box"                  # the Box on the Mac alone; built for macOS 26, the app runs without it before
ENTITLEMENTS = ROOT / "packaging" / "entitlements.plist"
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
    wanted = ["-e", f"{ROOT}[app,window,box]", "pyinstaller"]
    if SYSTEM == "windows":
        wanted.append("pythonnet<3.2")       # the bridge to .NET under the window: the series the build was tried with
    run(uv, "pip", "install", "--python", python, *wanted)
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

    Returns what is wrong, one line per file. The helper of the Box has a floor of its own.
    """
    problems = []
    for path in sorted(app.rglob("*")):
        if path.is_symlink() or not path.is_file() or not is_mach_o(path) or path.name == BOX_HELPER:
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


def sign(app: Path, identity: str) -> None:
    """Sign every program file from the inside out, then the app, all with the hardened runtime
    and a time stamp from Apple – notarisation accepts nothing less."""
    inner = [path for path in app.rglob("*") if path.is_file() and not path.is_symlink() and is_mach_o(path)
             and path.parent != app / "Contents" / "MacOS"]
    inner.sort(key=lambda path: len(path.parts), reverse=True)
    base = ["codesign", "--force", "--timestamp", "--options", "runtime", "--sign", identity]
    print(f"+ codesign: {len(inner)} program files, then the app", flush=True)
    for start in range(0, len(inner), 20):
        subprocess.run(base + [str(path) for path in inner[start:start + 20]], check=True, capture_output=True)
    run(*base, "--entitlements", ENTITLEMENTS, app)
    run("codesign", "--verify", "--deep", "--strict", app)


def notarize(path: Path, profile: str) -> None:
    """Have Apple check an app or a disk image and attach the ticket, so the first start works offline too."""
    upload = path
    if path.suffix == ".app":
        upload = BUILD / f"{path.stem}.zip"
        run("ditto", "-c", "-k", "--keepParent", path, upload)
    print(f"+ notarytool submit {upload.name} (this takes a few minutes)", flush=True)
    done = subprocess.run(["xcrun", "notarytool", "submit", str(upload), "--keychain-profile", profile, "--wait",
                           "--output-format", "json"], capture_output=True, text=True)
    try:
        answer = json.loads(done.stdout)
    except ValueError:
        answer = {}
    if answer.get("status") != "Accepted":
        if answer.get("id"):                 # Apple says what it did not like
            subprocess.run(["xcrun", "notarytool", "log", answer["id"], "--keychain-profile", profile])
        sys.exit(f"Not notarised: {answer.get('status') or done.stderr.strip() or done.stdout.strip()}")
    run("xcrun", "stapler", "staple", path)


def disk_image(app: Path, identity: str | None) -> Path:
    """The app next to a shortcut to the Applications folder, as people expect it."""
    stage = BUILD / "dmg"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    run("ditto", app, stage / app.name)
    (stage / "Applications").symlink_to("/Applications")
    image = DIST / DISK_IMAGE
    image.unlink(missing_ok=True)
    run("hdiutil", "create", "-volname", PRODUCT, "-srcfolder", stage, "-format", "UDZO", "-ov", image)
    if identity:
        run("codesign", "--force", "--timestamp", "--sign", identity, image)
    return image


def windows_zip(folder: Path) -> Path:
    """The program folder as one file to pass on; unpacked it is a folder with the program inside."""
    import zipfile

    target = DIST / WINDOWS_ZIP
    target.unlink(missing_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                archive.write(path, (Path(PRODUCT) / path.relative_to(folder)).as_posix())
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--here", action="store_true", help="use the Python that runs this script")
    parser.add_argument("--fresh", action="store_true", help="make the build environment anew")
    parser.add_argument("--no-box-helper", action="store_true",
                        help="macOS: leave out the helper that lets the Box run on the Mac alone "
                             "(it needs the Xcode tools of macOS 26 or newer to build)")
    parser.add_argument("--sign", metavar="IDENTITY", nargs="?", const="", default=None,
                        help="macOS: sign with this certificate (default: $GT7C_SIGN_IDENTITY)")
    parser.add_argument("--notarize", metavar="PROFILE", help="macOS: have Apple check the signed result")
    parser.add_argument("--dmg", action="store_true", help="macOS: pack the app into a disk image")
    args = parser.parse_args(argv)
    identity = None
    if args.sign is not None:
        identity = args.sign or os.environ.get("GT7C_SIGN_IDENTITY")
        if not identity:
            parser.error("--sign needs a certificate name, or GT7C_SIGN_IDENTITY")
    if (identity or args.notarize or args.dmg) and SYSTEM != "mac":
        parser.error("--sign, --notarize and --dmg are for macOS")
    if args.notarize and not identity:
        parser.error("--notarize needs --sign")

    python = Path(sys.executable) if args.here else environment(args.fresh)
    if SYSTEM == "mac":
        helper = BUILD / BOX_HELPER                  # the recipe packs it if it is there
        helper.unlink(missing_ok=True)
        if not args.no_box_helper:
            sys.path.insert(0, str(ROOT / "tools"))
            from build_box_helper import build as build_box_helper

            try:
                print("+ swiftc", build_box_helper(helper).relative_to(ROOT), flush=True)
            except RuntimeError as problem:
                sys.exit(f"{problem}\n\nThe helper of the Box could not be built; --no-box-helper builds without it.")
    run(python, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", DIST,
        "--workpath", BUILD / "pyinstaller", ROOT / "packaging" / "gt7companion.spec")

    if SYSTEM == "mac":
        app = DIST / f"{PRODUCT}.app"
        problems = check_macos_files(app)
        if problems:
            print(f"\nNot fit for macOS {MINIMUM_MACOS}:\n  " + "\n  ".join(problems), file=sys.stderr)
            return 1
        print(f"\n{app.relative_to(ROOT)}: every program file runs on macOS {MINIMUM_MACOS} or newer.")
        if identity:
            sign(app, identity)
        if args.notarize:
            notarize(app, args.notarize)
        if args.dmg:
            image = disk_image(app, identity)
            if args.notarize:
                notarize(image, args.notarize)
            print(f"\n{image.relative_to(ROOT)}")
    elif SYSTEM == "windows":
        print(f"\n{windows_zip(DIST / 'gt7companion').relative_to(ROOT)}")
    else:
        print(f"\n{(DIST / 'gt7companion').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
