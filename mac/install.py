#!/usr/bin/env python3
"""Guided Mac setup using native dialogs, without extra Python packages."""
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

import escape_pod_cast as publisher

HERE = Path(__file__).resolve().parent
HOME = Path.home() / 'Library/Application Support/Escape Pod Cast'
APP = Path.home() / 'Applications/Escape Pod Cast.app'
AGENT = Path.home() / 'Library/LaunchAgents/com.escapepodcast.publisher.plist'
DEFAULT_REPO = 'udeudeude/Escape-Pod-Cast'


class Cancelled(Exception):
    pass


def literal(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


def dialog(message, buttons=('Cancel', 'Continue'), text=None, hidden=False):
    script = 'set answer to display dialog %s with title "Escape Pod Cast" buttons {%s} default button %s' % (
        literal(message), ', '.join(literal(b) for b in buttons), literal(buttons[-1]))
    if 'Cancel' in buttons:
        script += ' cancel button "Cancel"'
    if text is not None:
        script += ' default answer ' + literal(text)
        if hidden:
            script += ' with hidden answer'
        script += '\nreturn (button returned of answer) & linefeed & (text returned of answer)'
    else:
        script += '\nreturn button returned of answer'
    # stdin keeps scripts and entered secrets out of process command arguments.
    result = subprocess.run(['/usr/bin/osascript', '-'], input=script,
                            capture_output=True, text=True)
    if result.returncode:
        if '(-128)' in result.stderr:
            raise Cancelled()
        raise RuntimeError('The Mac could not open the setup window.')
    values = result.stdout.rstrip('\n').split('\n', 1)
    return values[0], values[1] if len(values) == 2 else ''


def notify(message):
    print(message, flush=True)
    script = 'display notification %s with title "Escape Pod Cast"' % literal(message)
    subprocess.run(['/usr/bin/osascript', '-'], input=script,
                   capture_output=True, text=True)


def token_url(repo):
    return 'https://github.com/settings/personal-access-tokens/new?' + urllib.parse.urlencode({
        'name': 'Escape Pod Cast Mac',
        'description': 'Publish my personal podcast and enable its GitHub Pages feed.',
        'target_name': repo.split('/')[0],
        'expires_in': '365', 'contents': 'write', 'pages': 'write',
        'administration': 'write',
    })


def connect(repo):
    owner, name = repo.split('/', 1)
    dialog('One connection to GitHub is needed so this Mac can publish your audio.\n\n'
           'The next screen opens GitHub with the name and permissions filled in.\n\n'
           'On GitHub:\n'
           '1. Sign in as %s if asked.\n'
           '2. Choose “Only select repositories” and select %s.\n'
           '3. Click “Generate token”, then copy the token.\n\n'
           'Return to the Escape Pod Cast window and paste it. You only do this during setup.' % (owner, name),
           buttons=('Cancel', 'Open GitHub'))
    while True:
        subprocess.run(['/usr/bin/open', token_url(repo)], check=True)
        button, token = dialog('Finish on GitHub, then paste the copied token here.\n\n'
                               'Select “Only select repositories” → %s, then “Generate token”.\n'
                               'The pasted text stays hidden.' % name,
                               buttons=('Cancel', 'Connect'), text='', hidden=True)
        try:
            return publisher.setup(repo, token.strip(), progress=notify)
        except (publisher.Failure, OSError, ValueError) as exc:
            hint = str(exc)
            if '401' in hint:
                hint = 'GitHub did not accept this token. Copy the newly generated token and try again.'
            elif '403' in hint or '404' in hint:
                hint = ('Check that the token selects %s and has Contents, Pages, and Administration '
                        'set to Read and write. Then generate and copy it again.' % name)
            elif 'CERTIFICATE_VERIFY_FAILED' in hint:
                hint = ('Python needs its certificates installed. Open the Python folder in Applications '
                        'and run Install Certificates.command, then try again.')
            dialog('The connection is not ready yet.\n\n' + hint,
                   buttons=('Cancel', 'Try Again'))


def droplet_source(python, script, folder, log, feed_url):
    return '''on publishFiles(droppedFiles)
    set commandLine to quoted form of %s & " " & quoted form of %s & " --notify"
    repeat with droppedFile in droppedFiles
        set commandLine to commandLine & " " & quoted form of (POSIX path of droppedFile)
    end repeat
    do shell script commandLine & " >> " & quoted form of %s & " 2>&1 &"
    display notification "Uploading audio. You will see a completion message." with title "Escape Pod Cast"
end publishFiles
on open droppedFiles
    my publishFiles(droppedFiles)
end open
on run
    set selectedAction to choose from list {"Add audio…", "Open drop folder", "Copy podcast link", "Open publishing log"} with prompt "Choose an action, or drop audio straight onto the app icon." with title "Escape Pod Cast" default items {"Add audio…"} OK button name "Open"
    if selectedAction is false then return
    set selectedAction to item 1 of selectedAction
    if selectedAction is "Add audio…" then
        try
            set audioFiles to choose file with prompt "Choose audio for Apple Podcasts" with multiple selections allowed
            my publishFiles(audioFiles)
        on error number -128
            return
        end try
    else if selectedAction is "Open drop folder" then
        do shell script "/usr/bin/open " & quoted form of %s
    else if selectedAction is "Copy podcast link" then
        set the clipboard to %s
        display dialog "Podcast link copied. On your iPhone: Apple Podcasts → Library → ••• → Follow a Show by URL. Paste the link and enable automatic downloads." buttons {"OK"} default button "OK" with title "Escape Pod Cast"
    else if selectedAction is "Open publishing log" then
        do shell script "/usr/bin/touch " & quoted form of %s
        do shell script "/usr/bin/open " & quoted form of %s
    end if
end run
''' % tuple(literal(x) for x in (python, script, log, folder, feed_url, log, log))


def install_app(config):
    HOME.mkdir(parents=True, exist_ok=True)
    (HOME / 'Drop Audio Here').mkdir(exist_ok=True)
    script = HOME / 'escape_pod_cast.py'
    shutil.copy2(HERE / 'escape_pod_cast.py', script)
    applescript = droplet_source(sys.executable, script, HOME / 'Drop Audio Here',
                                HOME / 'Status.log', config['feed_url'])
    source = HOME / 'droplet.applescript'
    source.write_text(applescript)
    APP.parent.mkdir(parents=True, exist_ok=True)
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


def main():
    if sys.platform != 'darwin':
        raise RuntimeError('Open START-HERE.command on your Mac.')
    config = None
    if publisher.CONFIG.exists():
        try:
            config = json.loads(publisher.CONFIG.read_text())
        except (OSError, ValueError):
            pass
    repo = config['repo'] if config else DEFAULT_REPO
    button, _ = dialog('This installs Escape Pod Cast on your Mac.\n\n'
                       'After setup, drop audio onto the app to publish it for Apple Podcasts.\n\n'
                       'Your GitHub repository: %s\n'
                       'No payment method or other service is needed.\n\n'
                       'The feed and audio are publicly accessible, outside Apple’s catalog.' % repo,
                       buttons=('Cancel', 'Other Repository', 'Install'))
    if button == 'Other Repository':
        _, repo = dialog('Enter the GitHub repository for your own feed.',
                         text=repo)
        repo = repo.strip()
        if repo != (config or {}).get('repo'):
            config = None
    if not publisher.re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise RuntimeError('Enter a repository in the form owner/name.')
    if config is not None:
        # Reinstall without making the user create another working credential.
        try:
            client = publisher.GitHub(repo, publisher.get_token(repo))
            client.request('GET', '')
        except (publisher.Failure, OSError, ValueError):
            config = None
    if config is None:
        config = connect(repo)
    notify('Creating your Mac app…')
    install_app(config)
    subprocess.run(['/usr/bin/pbcopy'], input=config['feed_url'].encode(), check=True)
    subprocess.run(['/usr/bin/open', '-R', str(APP)], check=True)
    # The feed link may take time to become live. Do not label an untested URL ready.
    ready = False
    try:
        with urllib.request.urlopen(config['feed_url'], timeout=8) as response:
            root = publisher.ET.fromstring(response.read())
            ready = root.find('channel') is not None
    except (OSError, ValueError, publisher.ET.ParseError):
        pass
    status = ('Your feed is online.' if ready else
              'GitHub is preparing your feed; allow a few minutes before following it.')
    button, _ = dialog('Your Mac app is installed.\n\n'
                       '1. Open the app and choose “Add audio…” for your first file.\n'
                       '2. On iPhone: Apple Podcasts → Library → ••• → Follow a Show by URL.\n'
                       '3. Paste the podcast link and enable automatic downloads.\n\n'
                       '%s\n\n%s\n\n'
                       'The link is copied to your clipboard. The app can copy it again any time.' %
                       (config['feed_url'], status), buttons=('Done', 'Open App'))
    if button == 'Open App':
        subprocess.run(['/usr/bin/open', str(APP)], check=True)


if __name__ == '__main__':
    try:
        main()
    except Cancelled:
        sys.exit(0)
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        # Show the problem where the user is looking, not only in Terminal.
        print('Installation stopped: ' + str(exc), file=sys.stderr)
        try:
            dialog('Setup could not finish.\n\n' + str(exc), buttons=('OK',))
        except (Cancelled, RuntimeError, OSError):
            pass
        sys.exit(1)
