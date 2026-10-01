#!/bin/bash
set -eu
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
if ! command -v python3 >/dev/null 2>&1; then
    echo 'Install Python 3 from https://www.python.org/downloads/macos/ and run this again.'
    read -r -p 'Press Return to close.'
    exit 1
fi
if ! python3 mac/install.py; then
    read -r -p 'Press Return to close.'
    exit 1
fi
read -r -p 'Press Return to close.'
