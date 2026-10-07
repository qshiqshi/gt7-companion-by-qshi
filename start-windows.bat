@echo off
rem Gran Turismo 7 Companion by qshi - start on Windows (double-click this file).
rem The first start installs what the program needs into the folder ".venv" next to this file
rem (a few minutes, needs the internet). Later starts are quick.
rem NOTE: this script has not been tested on a real Windows computer yet.
setlocal
cd /d "%~dp0"

set "PYTHON="
where py >nul 2>nul && py -3 -c "import sys; raise SystemExit(sys.version_info < (3, 12))" >nul 2>nul && set "PYTHON=py -3"
if not defined PYTHON (
  where python >nul 2>nul && python -c "import sys; raise SystemExit(sys.version_info < (3, 12))" >nul 2>nul && set "PYTHON=python"
)
if not defined PYTHON (
  echo.
  echo Python 3.12 or newer is missing.
  echo Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) and start this file again.
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo First start: setting up ^(this takes a few minutes^) ...
  %PYTHON% -m venv .venv
  if errorlevel 1 (
    echo Setting up failed.
    pause
    exit /b 1
  )
)
if not exist ".venv\installed" (
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -e ".[app,box]"
  if errorlevel 1 (
    echo.
    echo Installing failed ^(is the internet connected?^).
    pause
    exit /b 1
  )
  echo done> ".venv\installed"
)

echo Starting. A symbol appears in the tray next to the clock; the dashboard opens in your browser.
echo This window can stay open in the background. Quit with the symbol in the tray.
".venv\Scripts\python.exe" -m gt7companion.launcher %*
if errorlevel 1 pause
