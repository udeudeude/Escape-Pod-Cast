#!/bin/bash
set -eu
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
# Prefer a Python with the window toolkit already included. Apple's command-line
# Python may lack it; the app retains its native menu fallback in that case.
EPC_PYTHON=""
for EPC_CANDIDATE in /Library/Frameworks/Python.framework/Versions/Current/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3; do
    if [ -x "$EPC_CANDIDATE" ] && "$EPC_CANDIDATE" -c 'import tkinter; assert tkinter.TkVersion >= 8.6' >/dev/null 2>&1; then
        EPC_PYTHON="$EPC_CANDIDATE"
        break
    fi
done
if [ -n "$EPC_PYTHON" ]; then
    exec "$EPC_PYTHON" mac/install.py
fi
if ! command -v python3 >/dev/null 2>&1; then
    /usr/bin/osascript <<'APPLESCRIPT'
display dialog "Escape Pod Cast needs Python 3 on this Mac.\n\nClick Open Download, install the macOS package, then open START-HERE.command again." with title "Escape Pod Cast" buttons {"Cancel", "Open Download"} default button "Open Download" cancel button "Cancel"
APPLESCRIPT
    /usr/bin/open 'https://www.python.org/downloads/macos/'
    exit 1
fi
# All setup questions and errors appear in native Mac windows.
exec python3 mac/install.py
