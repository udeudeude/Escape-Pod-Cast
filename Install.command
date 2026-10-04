#!/bin/bash
set -eu
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
if ! command -v python3 >/dev/null 2>&1; then
    /usr/bin/osascript <<'APPLESCRIPT'
display dialog "Escape Pod Cast needs Python 3 on this Mac.\n\nClick Open Download, install the macOS package, then open START-HERE.command again." with title "Escape Pod Cast" buttons {"Cancel", "Open Download"} default button "Open Download" cancel button "Cancel"
APPLESCRIPT
    /usr/bin/open 'https://www.python.org/downloads/macos/'
    exit 1
fi
# All setup questions and errors appear in native Mac windows.
exec python3 mac/install.py
