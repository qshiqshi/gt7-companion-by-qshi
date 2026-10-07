#!/bin/bash
# Gran Turismo 7 Companion by qshi – start on a Mac (double-click this file).
# The first start installs what the program needs into the folder ".venv" next to this file
# (a few minutes, needs the internet). Later starts are quick.
cd "$(dirname "$0")" || exit 1

PYTHON=""
for candidate in python3.14 python3.13 python3.12 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 12))' 2>/dev/null; then
    PYTHON="$candidate"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  echo
  echo "Python 3.12 or newer is missing."
  echo "Install it from https://www.python.org/downloads/ and start this file again."
  echo
  read -r -p "Press Return to close."
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "First start: setting up (this takes a few minutes) ..."
  "$PYTHON" -m venv .venv || { read -r -p "Setting up failed. Press Return to close."; exit 1; }
fi
# Install or update whenever the list of needed packages changed.
if [ ! -f .venv/installed ] || [ pyproject.toml -nt .venv/installed ]; then
  .venv/bin/python -m pip install --quiet --upgrade pip
  if .venv/bin/python -m pip install --quiet -e ".[app,box]"; then
    touch .venv/installed
  else
    echo
    read -r -p "Installing failed (is the internet connected?). Press Return to close."
    exit 1
  fi
fi

echo "Starting. A symbol appears in the menu bar; the dashboard opens in your browser."
echo "This window can stay open in the background. Quit with the symbol in the menu bar."
exec .venv/bin/python -m gt7companion.launcher "$@"
