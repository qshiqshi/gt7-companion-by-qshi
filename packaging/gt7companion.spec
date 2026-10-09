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
         (str(ROOT / "LICENSE"), "."), (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
         (str(ROOT / "TEXT_QUOTES.md"), ".")]
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
details = None
if sys.platform == "win32":
    # What Windows shows for the program: in the question of the firewall, the task manager, the file's properties.
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                     VarFileInfo, VarStruct, VSVersionInfo)

    numbers = tuple(int(part) for part in (__version__.split(".") + ["0"] * 4)[:4])
    details = VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers, mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1,
                          subtype=0x0, date=(0, 0)),
        kids=[StringFileInfo([StringTable("040904B0", [
                  StringStruct("CompanyName", "qshi"),
                  StringStruct("FileDescription", WINDOW_TITLE),
                  StringStruct("FileVersion", __version__),
                  StringStruct("InternalName", "gt7companion"),
                  StringStruct("LegalCopyright", "GPL-3.0-or-later. Not affiliated with Sony Interactive "
                                                 "Entertainment or Polyphony Digital."),
                  StringStruct("OriginalFilename", "gt7companion.exe"),
                  StringStruct("ProductName", APP_NAME),
                  StringStruct("ProductVersion", __version__)])]),
              VarFileInfo([VarStruct("Translation", [0x0409, 1200])])])

archive = PYZ(analysis.pure)
program = EXE(archive, analysis.scripts, [], exclude_binaries=True, name="gt7companion",
              console=False, upx=False, version=details,
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
