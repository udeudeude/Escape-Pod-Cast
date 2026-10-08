#!/usr/bin/env python3
"""Build a portable, unsigned Mac setup .app using only standard-library files.

The executable is a shell script, so it carries no newer-macOS Mach-O minimum.
Setup compiles the publishing droplet on the user's own Mac. Python/Tk is still
required; the existing setup flow offers the official installer if missing.
"""
from pathlib import Path
import plistlib
import re
import shutil
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(destination):
    version = re.search(r"APP_VERSION = '([^']+)'", (ROOT / 'mac/app.py').read_text()).group(1)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / ('Escape-Pod-Cast-Mac-' + version + '.zip')
    with tempfile.TemporaryDirectory() as temp:
        app = Path(temp) / 'Escape Pod Cast Setup.app'
        contents = app / 'Contents'
        resources, executables = contents / 'Resources', contents / 'MacOS'
        resources.mkdir(parents=True)
        executables.mkdir()
        shutil.copytree(ROOT / 'mac', resources / 'mac', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copy2(ROOT / 'Install.command', resources / 'Install.command')
        launcher = executables / 'setup'
        launcher.write_text('#!/bin/bash\nset -eu\ncd "$(dirname "$0")/../Resources"\nexec /bin/bash ./Install.command\n')
        launcher.chmod(0o755)
        (contents / 'Info.plist').write_bytes(plistlib.dumps({
            'CFBundleName': 'Escape Pod Cast Setup', 'CFBundleDisplayName': 'Escape Pod Cast Setup',
            'CFBundleIdentifier': 'com.escapepodcast.setup', 'CFBundleExecutable': 'setup',
            'CFBundlePackageType': 'APPL', 'CFBundleVersion': version,
            'CFBundleShortVersionString': version, 'LSMinimumSystemVersion': '11.0', 'LSUIElement': True,
        }))
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
            for path in sorted(app.rglob('*')):
                if path.is_file():
                    output.write(path, path.relative_to(app.parent))
    return archive


if __name__ == '__main__':
    print(build(ROOT / 'dist'))
