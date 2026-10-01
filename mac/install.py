#!/usr/bin/env python3
"""Build a macOS droplet and install its per-user folder/cleanup monitor."""
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
HOME = Path.home() / 'Library/Application Support/Escape Pod Cast'
APP = Path.home() / 'Applications/Escape Pod Cast.app'
AGENT = Path.home() / 'Library/LaunchAgents/com.escapepodcast.publisher.plist'


def literal(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


def main():
    if sys.platform != 'darwin':
        raise RuntimeError('Install.command must run on your Mac.')
    HOME.mkdir(parents=True, exist_ok=True)
    (HOME / 'Drop Audio Here').mkdir(exist_ok=True)
    script = HOME / 'escape_pod_cast.py'
    shutil.copy2(HERE / 'escape_pod_cast.py', script)
    repo = input('GitHub repository [udeudeude/Escape-Pod-Cast]: ').strip()
    repo = repo or 'udeudeude/Escape-Pod-Cast'
    subprocess.run([sys.executable, str(script), '--setup', repo], check=True)
    # Python writes completion/failure dialogs; the droplet remains responsive.
    applescript = '''on open droppedFiles
    set commandLine to quoted form of %s & " " & quoted form of %s & " --notify"
    repeat with droppedFile in droppedFiles
        set commandLine to commandLine & " " & quoted form of (POSIX path of droppedFile)
    end repeat
    do shell script commandLine & " >> " & quoted form of %s & " 2>&1 &"
    display notification "Uploading audio. You will see a completion message." with title "Escape Pod Cast"
end open
on run
    do shell script "/usr/bin/open " & quoted form of %s
    display dialog "Drop audio onto this app or into the folder that just opened. Your feed URL is in Feed URL.txt beside that folder. Publishing status is in Status.log." buttons {"OK"} default button "OK" with title "Escape Pod Cast"
end run
''' % tuple(literal(x) for x in (sys.executable, script, HOME / 'Status.log', HOME / 'Drop Audio Here'))
    source = HOME / 'droplet.applescript'
    source.write_text(applescript)
    APP.parent.mkdir(parents=True, exist_ok=True)
    # Compile a new bundle first. Do not destroy the current app on compiler error.
    staging = APP.with_name('Escape Pod Cast new.app')
    if staging.exists():
        shutil.rmtree(staging)
    subprocess.run(['/usr/bin/osacompile', '-o', str(staging), str(source)], check=True)
    if APP.exists():
        shutil.rmtree(APP)
    staging.rename(APP)
    definition = {
        'Label': 'com.escapepodcast.publisher',
        'ProgramArguments': [sys.executable, str(script), '--maintain'],
        'RunAtLoad': True, 'StartInterval': 60,
        'StandardOutPath': str(HOME / 'Status.log'),
        'StandardErrorPath': str(HOME / 'Status.log'),
        'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin'},
    }
    AGENT.parent.mkdir(parents=True, exist_ok=True)
    AGENT.write_bytes(plistlib.dumps(definition))
    target = 'gui/%s' % os.getuid()
    subprocess.run(['/bin/launchctl', 'bootout', target, str(AGENT)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(['/bin/launchctl', 'bootstrap', target, str(AGENT)], check=True)
    # Keep the subscription address visible and copy it for easy transfer.
    config = json.loads((HOME / 'config.json').read_text())
    subprocess.run(['/usr/bin/pbcopy'], input=config['feed_url'].encode(), check=True)
    subprocess.run(['/usr/bin/open', '-R', str(APP)], check=True)
    subprocess.run(['/usr/bin/open', str(HOME / 'Feed URL.txt')], check=True)
    print('\nInstalled. Drag the app into your Dock if you like.\n'
          'Your feed URL is copied to the clipboard. Add it once in Apple Podcasts.\n'
          'Nothing is submitted to Apple’s catalog. Audio is publicly accessible.\n'
          'Originals dropped onto the app stay untouched; folder uploads move into Published.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print('Installation stopped: ' + str(exc), file=sys.stderr)
        sys.exit(1)
