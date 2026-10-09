# Building the program for Windows

The Windows program is the same code as the Mac app: the dashboard in a window of its own
(WebView2), a symbol next to the clock, the web server for tablets and OBS. PyInstaller packs it
into a folder; the build script zips that folder as
`dist/GT7-Companion-by-qshi-windows-x64.zip`. There is no installer and no signature.

## What you need

- Windows 10 or 11, on an Intel/AMD computer or on ARM (there Windows 11, which runs x64
  programs). The build always uses the x64 Python: the libraries under the window exist for
  x64 only.
- [uv](https://docs.astral.sh/uv/getting-started/installation/). It downloads the Python for
  the build; none has to be installed.
- The source of this repository.

## Build

    uv run --no-project packaging\build.py

The first run makes the build environment in `build\venv-windows` (Python 3.13 for x64 and the
packages in the versions of `packaging\constraints.txt`). Then PyInstaller writes the program to
`dist\gt7companion\` and the script packs the ZIP. `--fresh` makes the environment anew.

On an ARM computer PyInstaller warns that it cannot find some libraries of Windows itself
(`ntdll.dll`, `WINMM.dll`, `bcrypt.dll` and the like). They are never packed – every Windows has
them – so the warnings mean nothing for the result.

## Tests

    uv venv --python cpython-3.13.12-windows-x86_64-none .venv
    uv pip install --python .venv\Scripts\python.exe -c packaging\constraints.txt -e ".[dev,app,window,box]"
    .venv\Scripts\python.exe -m unittest discover -s tests

Tests that need a browser, a Mac or the helper of the Box are skipped.

## What the program needs where it runs

- The WebView2 runtime: part of Windows 11 and of an up-to-date Windows 10. Without it the
  program shows only its symbol and opens the dashboard in the browser.
- .NET Framework 4.6.2 or newer: part of Windows 10 and 11.

Settings, own layouts and the log (`companion.log`) are in
`%LOCALAPPDATA%\gt7-companion-by-qshi`, not in the program's folder.

## What to expect

- **Not signed.** After a download SmartScreen says "Windows protected your PC": **More info** →
  **Run anyway**.
- **The first start is slow.** Defender reads every file of the new folder once and WebView2 sets
  up its profile. Later starts take a second or two.
- **The firewall asks once**, when the program first listens for the PlayStation (UDP 33740) or
  shares the dashboard in the home network. It has to be allowed for private networks.
- **Closing the window hides it.** The symbol next to the clock brings it back and quits the
  program; so does starting the program a second time (that only shows the window of the first).
  Without a symbol, closing the window ends the program.
- **The Box speaks with Gemini** (a key of your own). The voice and the language model of the
  computer itself are a Mac thing, and "Hey Box" needs a speech model that is too large to pack.

## What was checked, and what was not

Checked on 2026-10-09 in a virtual machine: Windows 11 Home 24H2 on ARM (the x64 program runs
there in emulation), WebView2 154.

- the tests of the project;
- the built program starts, its window shows the dashboard with the demo drive, the symbol is
  there;
- a second start ends at once and leaves one program running; closing the window hides it and
  the program keeps serving; the second start brings the window back;
- switched to the PlayStation, it receives the packets of the stand-in console
  (`tools/fake_console.py`, format C) and shows them;
- Microsoft Defender, with the signatures of that day, finds nothing in the ZIP or in the folder.

Not checked: a real PC with an Intel or AMD processor, Windows 10, the SmartScreen dialog after a
download, sound and microphone (the Box), a real PlayStation (the virtual machine sits behind
the Mac), displays with scaling, several screens.

## How the virtual machine was driven

For the record, because it took a while to find: UTM's `utmctl exec` returns at once and gives
no output back, so every step wrote its log and exit code into files that `utmctl file pull`
fetched. A program that needs the desktop (the window) was started by a scheduled task without
a trigger, in the session of the logged-on user. Everything stayed in one folder
(`C:\gt7c-build`: uv, Python, caches, source, result), and the machine ran as a throwaway copy
(`utmctl start --disposable`), so nothing of it was kept.
