# PyInstaller recipe: a folder with the program for the system it is built on.
#
#     python packaging/build.py
#
# macOS: dist/GT7 Companion by qshi.app (symbol in the menu bar, no Dock icon)
# Windows/Linux: dist/gt7companion/ with the program inside (symbol in the tray)
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
SOURCE = ROOT / "src"
sys.path.insert(0, str(SOURCE))
from gt7companion import APP_NAME, __version__          # noqa: E402

hidden = (collect_submodules("uvicorn") + collect_submodules("websockets") + collect_submodules("pystray")
          + ["gt7companion.app", "segno", "ifaddr", "Crypto.Cipher.Salsa20"])
try:                                                    # the Box on the loudspeakers, if it is installed
    import sounddevice  # noqa: F401
    hidden.append("sounddevice")
except (ImportError, OSError):
    pass

analysis = Analysis(
    [str(ROOT / "packaging" / "app_entry.py")],
    pathex=[str(SOURCE)],
    datas=[(str(SOURCE / "gt7companion" / "web"), "gt7companion/web"),
           (str(SOURCE / "gt7companion" / "data"), "gt7companion/data"),
           (str(ROOT / "LICENSE"), "."), (str(ROOT / "THIRD_PARTY_NOTICES.md"), ".")],
    hiddenimports=hidden,
    excludes=["tkinter", "numpy", "playwright", "fontTools", "PyInstaller"],
)
archive = PYZ(analysis.pure)
program = EXE(archive, analysis.scripts, [], exclude_binaries=True, name="gt7companion",
              console=False, upx=False)
folder = COLLECT(program, analysis.binaries, analysis.datas, name="gt7companion", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        folder,
        name="GT7 Companion by qshi.app",
        bundle_identifier="de.qshi.gt7companion",
        version=__version__,
        info_plist={
            "CFBundleDisplayName": "GT7 Companion by qshi",
            "CFBundleShortVersionString": __version__,
            "LSUIElement": True,                        # lives in the menu bar, no Dock icon
            "LSMinimumSystemVersion": "12.0",
            "NSHighResolutionCapable": True,
            "NSLocalNetworkUsageDescription":
                "Receives the telemetry of Gran Turismo 7 from your PlayStation and shows the dashboard "
                "on devices in your home network.",
            "NSMicrophoneUsageDescription":
                "Records your question while you hold the talk button, to send it to the race engineer.",
            "NSHumanReadableCopyright": f"{APP_NAME} – GPL-3.0-or-later. Not affiliated with Sony Interactive "
                                        "Entertainment or Polyphony Digital.",
        },
    )
