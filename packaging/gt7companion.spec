# PyInstaller recipe: the program for the system it is built on.
#
#     python packaging/build.py
#
# macOS: dist/GT7 Companion by qshi.app (window, Dock icon, symbol in the menu bar)
# Windows/Linux: dist/gt7companion/ with the program inside (window on Windows, symbol in the tray)
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
SOURCE = ROOT / "src"
PACKAGING = ROOT / "packaging"
sys.path.insert(0, str(SOURCE))
from gt7companion import APP_NAME, __version__          # noqa: E402
from gt7companion.launcher import WINDOW_TITLE          # noqa: E402

hidden = (collect_submodules("uvicorn") + collect_submodules("websockets") + collect_submodules("pystray")
          + ["gt7companion.app", "segno", "ifaddr", "Crypto.Cipher.Salsa20",
             "sounddevice",                             # the Box on the loudspeakers
             "webview"])                                # the window; its hook brings the platform parts
datas = [(str(SOURCE / "gt7companion" / "web"), "gt7companion/web"),
         (str(SOURCE / "gt7companion" / "data"), "gt7companion/data"),
         (str(ROOT / "LICENSE"), "."), (str(ROOT / "THIRD_PARTY_NOTICES.md"), ".")]
binaries = []
if sys.platform == "darwin":
    datas += [(str(PACKAGING / "mac" / f"{language}.lproj" / "InfoPlist.strings"), f"{language}.lproj")
              for language in ("en", "de")]
    helper = ROOT / "build" / "gt7c-box"                # the Box on the Mac alone; packaging/build.py compiles it
    if helper.is_file():
        binaries.append((str(helper), "."))

analysis = Analysis(
    [str(PACKAGING / "app_entry.py")],
    pathex=[str(SOURCE)],
    datas=datas,
    binaries=binaries,
    hiddenimports=hidden,
    # Whisper is far too large to bundle; on a Mac the helper above recognises speech instead.
    excludes=["tkinter", "numpy", "playwright", "fontTools", "PyInstaller", "mlx", "mlx_whisper", "torch",
              "faster_whisper", "numba", "scipy"],
)
archive = PYZ(analysis.pure)
program = EXE(archive, analysis.scripts, [], exclude_binaries=True, name="gt7companion",
              console=False, upx=False,
              icon=str(PACKAGING / ("icon.icns" if sys.platform == "darwin" else "icon.ico")))
folder = COLLECT(program, analysis.binaries, analysis.datas, name="gt7companion", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        folder,
        name=f"{WINDOW_TITLE}.app",
        icon=str(PACKAGING / "icon.icns"),
        bundle_identifier="de.qshi.gt7companion",
        version=__version__,
        info_plist={
            "CFBundleDisplayName": WINDOW_TITLE,
            "CFBundleShortVersionString": __version__,
            "CFBundleDevelopmentRegion": "en",
            "CFBundleLocalizations": ["en", "de"],      # menus of the system and the pages follow the user's language
            "LSMinimumSystemVersion": "14.0",
            "LSMultipleInstancesProhibited": True,      # a second start brings the window of the first to the front
            "LSApplicationCategoryType": "public.app-category.utilities",
            "NSHighResolutionCapable": True,
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},    # the window loads http://127.0.0.1
            "NSLocalNetworkUsageDescription":
                "Receives the telemetry of Gran Turismo 7 from your PlayStation and shows the dashboard "
                "on devices in your home network.",
            "NSMicrophoneUsageDescription":
                "Hears your question to the race engineer: while you hold the talk button or, if you switch "
                "that on, after you say \"Hey Box\".",
            "NSHumanReadableCopyright": f"{APP_NAME} – GPL-3.0-or-later. Not affiliated with Sony Interactive "
                                        "Entertainment or Polyphony Digital.",
        },
    )
