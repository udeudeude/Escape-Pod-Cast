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

import escape_pod_cast as publisher

HERE = Path(__file__).resolve().parent
HOME = Path.home() / 'Library/Application Support/Escape Pod Cast'
APP = Path.home() / 'Applications/Escape Pod Cast.app'
AGENT = Path.home() / 'Library/LaunchAgents/com.escapepodcast.publisher.plist'
SOURCE_REPO = 'udeudeude/Escape-Pod-Cast'


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


def choose_repository(config=None):
    if config:
        action, _ = dialog('Update Escape Pod Cast for your existing feed?\n\n'
                           'Repository: %s\n\n'
                           'Setup keeps your episodes and saved connection. If needed, it replaces '
                           'the old predictable feed address with a random one.' % config['repo'],
                           buttons=('Cancel', 'Other Repository', 'Update'))
        if action == 'Update':
            return config['repo']
    action, _ = dialog('Escape Pod Cast turns audio on your Mac into episodes in Apple Podcasts.\n\n'
                       'Each person uses their own GitHub account and repository. '
                       'No payment method or shared publishing service is needed.\n\n'
                       'Your feed gets a random address. The repository and audio remain public.\n\n'
                       'Create your own copy, or connect a copy you already have.',
                       buttons=('Cancel', 'Use Existing', 'Create My Copy'))
    if action == 'Create My Copy':
        subprocess.run(['/usr/bin/open', 'https://github.com/' + SOURCE_REPO + '/fork'], check=True)
        message = ('On GitHub:\n'
                   '1. Sign in to your own account.\n'
                   '2. Choose your account as Owner; keep the repository name or choose your own.\n'
                   '3. Click “Create fork”.\n\n'
                   'Then enter the owner/repository shown at the top of your new copy, '
                   'for example yourname/Escape-Pod-Cast.')
    else:
        message = 'Enter your GitHub copy as owner/repository, for example yourname/Escape-Pod-Cast.'
    while True:
        _, repo = dialog(message, text='', buttons=('Cancel', 'Continue'))
        repo = repo.strip()
        if publisher.re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
            return repo
        message = 'Enter both parts, separated by /, for example yourname/Escape-Pod-Cast.'


def connect(repo, token=None):
    owner, name = repo.split('/', 1)
    if token is None:
        action, _ = dialog('One connection to GitHub is needed so this Mac can publish your audio.\n\n'
           'The next screen opens GitHub with the name and permissions filled in.\n\n'
           'On GitHub:\n'
           '1. Sign in as %s if asked.\n'
           '2. Choose “Only select repositories” and select %s.\n'
           '3. Click “Generate token”, then copy the token.\n\n'
           'If you already created a token, choose “Paste Token” to use it.' % (owner, name),
           buttons=('Cancel', 'Open GitHub', 'Paste Token'))
        if action == 'Open GitHub':
            subprocess.run(['/usr/bin/open', token_url(repo)], check=True)
    while True:
        if token is None:
            action, pasted = dialog('Paste your existing GitHub token here.\n\n'
                                    'If you need to create one, choose “Open GitHub”, select '
                                    '“Only select repositories” → %s, then generate and copy it.\n\n'
                                    'The pasted text stays hidden.' % name,
                                    buttons=('Cancel', 'Open GitHub', 'Connect'), text='', hidden=True)
            if action == 'Open GitHub':
                subprocess.run(['/usr/bin/open', token_url(repo)], check=True)
                continue
            token = pasted.strip()
        try:
            return publisher.setup(repo, token, progress=notify)
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
            action, _ = dialog('The connection is not ready yet.\n\n' + hint +
                               '\n\n“Try Again” reuses the same token.',
                               buttons=('Cancel', 'Replace Token', 'Try Again'))
            if action == 'Replace Token':
                token = None


def droplet_source(python, script, folder, log, feed_url):
    return '''on runPublisher(argumentsList)
    set commandLine to quoted form of %s & " " & quoted form of %s & " --notify"
    repeat with argumentText in argumentsList
        set commandLine to commandLine & " " & quoted form of (argumentText as text)
    end repeat
    do shell script commandLine & " >> " & quoted form of %s & " 2>&1 &"
    display notification "Working. You will see a completion message; downloads may take a few minutes." with title "Escape Pod Cast"
end runPublisher
on publishFiles(droppedFiles)
    set paths to {}
    repeat with droppedFile in droppedFiles
        set end of paths to POSIX path of droppedFile
    end repeat
    my runPublisher(paths)
end publishFiles
on open droppedFiles
    my publishFiles(droppedFiles)
end open
on open location linkURL
    my runPublisher({"--youtube", linkURL})
end open location
on run
    set selectedAction to choose from list {"Add audio…", "Paste YouTube link…", "Set up / update YouTube…", "Open drop folder", "Copy podcast link", "Open publishing log"} with prompt "Choose an action, or drop audio or a saved YouTube link file onto the app icon." with title "Escape Pod Cast" default items {"Add audio…"} OK button name "Open"
    if selectedAction is false then return
    set selectedAction to item 1 of selectedAction
    if selectedAction is "Add audio…" then
        try
            set audioFiles to choose file with prompt "Choose audio for Apple Podcasts" with multiple selections allowed
            my publishFiles(audioFiles)
        on error number -128
            return
        end try
    else if selectedAction is "Paste YouTube link…" then
        try
            set suggestedLink to ""
            try
                set clipboardText to the clipboard as text
                if clipboardText starts with "https://" or clipboardText starts with "http://" then set suggestedLink to clipboardText
            end try
            set answer to display dialog "Paste a link to one YouTube video. Only import audio you have permission to copy and publicly host. Live streams and playlists are not supported." default answer suggestedLink buttons {"Cancel", "Get Audio"} default button "Get Audio" cancel button "Cancel" with title "Escape Pod Cast"
            my runPublisher({"--youtube", text returned of answer})
        on error number -128
            return
        end try
    else if selectedAction is "Set up / update YouTube…" then
        my runPublisher({"--youtube-setup"})
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
    previous_url = (config or {}).get('feed_url')
    repo = choose_repository(config)
    if not publisher.re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise RuntimeError('Enter a repository in the form owner/name.')
    token = None
    if config is not None and repo == config.get('repo'):
        # Reinstall without making the user create another working credential.
        try:
            token = publisher.get_token(repo)
        except (publisher.Failure, OSError, ValueError):
            pass
    config = connect(repo, token)
    notify('Creating your Mac app…')
    install_app(config)
    subprocess.run(['/usr/bin/pbcopy'], input=config['feed_url'].encode(), check=True)
    subprocess.run(['/usr/bin/open', '-R', str(APP)], check=True)
    # The feed link may take time to become live. Do not label an untested URL ready.
    ready = False
    try:
        root = publisher.ET.fromstring(publisher.public_bytes(config['feed_url']))
        ready = root.find('channel') is not None
    except (publisher.Failure, OSError, ValueError, publisher.ET.ParseError):
        pass
    status = ('Your feed is online.' if ready else
              'GitHub is preparing your feed; allow a few minutes before following it.')
    if previous_url and previous_url != config['feed_url']:
        status += ('\n\nYour podcast address has changed. Follow this new link in Apple Podcasts. '
                   'The old predictable feed is removed; existing episodes are kept.')
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
