#!/usr/bin/env python3
"""Local podcast publisher. Standard library only; no application server."""
import argparse
import base64
import contextlib
import datetime as dt
import email.utils
import fcntl
import getpass
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

HOME = Path.home() / 'Library/Application Support/Escape Pod Cast'
CONFIG = HOME / 'config.json'
SERVICE = 'Escape Pod Cast GitHub'
NS = 'http://www.itunes.com/dtds/podcast-1.0.dtd'
ET.register_namespace('itunes', NS)
RETENTION = dt.timedelta(days=14)
MEDIA_NAME = re.compile(r'^epc-[0-9a-f]{64}\.(mp3|m4a)$')


class Failure(RuntimeError):
    pass


class NetworkFailure(Failure):
    pass


def curl_value(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace(
        '\r', '\\r').replace('\n', '\\n') + '"'


def mac_transfer(url, method='GET', headers=None, data=None, upload=None,
                 follow=False, max_time=120, max_size=None):
    """Use macOS's working curl path; keep authorization in stdin, never argv."""
    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        output, header_file = folder / 'response', folder / 'headers'
        args = ['/usr/bin/curl', '-q', '--silent', '--show-error',
                '--connect-timeout', '15', '--max-time', str(max_time),
                '--proto', '=https', '--request', method,
                '--output', str(output), '--dump-header', str(header_file),
                '--write-out', '%{http_code}', '--config', '-']
        config = 'url = ' + curl_value(url) + '\n'
        for name, value in (headers or {}).items():
            config += 'header = ' + curl_value(name + ': ' + value) + '\n'
        if follow:
            args.extend(['--location', '--max-redirs', '5', '--proto-redir', '=https'])
        if method == 'HEAD':
            args.append('--head')
        if data is not None:
            payload = folder / 'request'
            payload.write_bytes(data)
            args.extend(['--data-binary', '@' + str(payload)])
        if upload is not None:
            args.extend(['--upload-file', str(upload)])
        if max_size is not None:
            args.extend(['--max-filesize', str(max_size)])
        result = subprocess.run(args, input=config, capture_output=True, text=True)
        if result.returncode:
            messages = {
                5: 'The configured network proxy could not be found.',
                6: 'The server address could not be found.',
                7: 'The server could not be reached.',
                28: 'The connection timed out.',
                60: 'macOS could not verify the server certificate.',
                63: 'The server did not respect the requested audio byte range.',
            }
            raise NetworkFailure(messages.get(result.returncode, 'The network request failed.') +
                                 ' Check your connection and try again with the same GitHub token.')
        try:
            status = int(result.stdout.strip())
        except ValueError:
            raise NetworkFailure('The network tool returned an unreadable response.') from None
        response_headers = {}
        if header_file.exists():
            for line in header_file.read_text(errors='replace').splitlines():
                if line.startswith('HTTP/'):
                    response_headers = {}  # Only the final response after redirects.
                elif ':' in line:
                    key, value = line.split(':', 1)
                    response_headers[key.lower()] = value.strip()
        return status, output.read_bytes() if output.exists() else b'', response_headers


def public_bytes(url):
    if sys.platform == 'darwin':
        status, data, _ = mac_transfer(url, follow=True, max_time=10)
        if status != 200:
            raise Failure('The public feed is not available yet (%s).' % status)
        return data
    with urllib.request.urlopen(url, timeout=8) as response:
        return response.read()


class GitHub:
    def __init__(self, repo, token):
        self.repo, self.token = repo, token
        self.base = 'https://api.github.com/repos/' + repo

    def headers(self):
        return {'Authorization': 'Bearer ' + self.token,
                'Accept': 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
                'User-Agent': 'Escape-Pod-Cast'}

    def request(self, method, path, body=None, missing=False):
        data = None if body is None else json.dumps(body).encode()
        headers = self.headers()
        if data is not None:
            headers['Content-Type'] = 'application/json'
        if sys.platform == 'darwin':
            status, raw, _ = mac_transfer(self.base + path, method, headers, data=data)
            if missing and status == 404:
                return None
            if status >= 400:
                raise Failure('GitHub returned %s for %s %s. Check token permissions, '
                              'expiration, connection, and repository access.' %
                              (status, method, path))
            return json.loads(raw) if raw else None
        req = urllib.request.Request(self.base + path, data=data,
                                     headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            if missing and exc.code == 404:
                return None
            raise Failure('GitHub returned %s for %s %s. Check token permissions, '
                          'expiration, connection, and repository access.' %
                          (exc.code, method, path)) from None

    def assets(self, release):
        result, page = [], 1
        while True:
            batch = self.request('GET', '/releases/%s/assets?per_page=100&page=%s' %
                                 (release['id'], page))
            result.extend(batch)
            if len(batch) < 100:
                return result
            page += 1

    def upload(self, release, path, name, mime):
        # Stream from disk; do not hold a potentially 2 GiB episode in memory.
        url = urllib.parse.urlsplit(release['upload_url'].split('{')[0])
        if url.scheme != 'https' or url.hostname != 'uploads.github.com':
            raise Failure('Unexpected GitHub upload endpoint.')
        if sys.platform == 'darwin':
            headers = self.headers()
            headers['Content-Type'] = mime
            status, raw, _ = mac_transfer(release['upload_url'].split('{')[0] +
                                         '?name=' + name, 'POST', headers,
                                         upload=path, max_time=900)
            if status != 201:
                raise Failure('Audio upload failed (%s). Retry the original file; '
                              'completed uploads are reused.' % status)
            return json.loads(raw)
        connection = http.client.HTTPSConnection(url.hostname, timeout=900)
        headers = self.headers()
        headers.update({'Content-Type': mime, 'Content-Length': str(path.stat().st_size)})
        try:
            with path.open('rb') as stream:
                connection.request('POST', url.path + '?name=' + name,
                                   body=stream, headers=headers)
                response = connection.getresponse()
                raw = response.read()
                if response.status != 201:
                    raise Failure('Audio upload failed (%s). Retry the original file; '
                                  'completed uploads are reused.' % response.status)
                return json.loads(raw)
        finally:
            connection.close()

    def read_feed(self):
        item = self.request('GET', '/contents/docs/feed.xml?ref=main')
        return ET.fromstring(base64.b64decode(item['content'])), item['sha']

    def write_feed(self, root, sha):
        content = ET.tostring(root, encoding='utf-8', xml_declaration=True)
        return self.request('PUT', '/contents/docs/feed.xml', {
            'message': 'Update personal podcast episodes', 'branch': 'main',
            'sha': sha, 'content': base64.b64encode(content).decode()})


def stamp(value):
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00'))


def channel(root):
    result = root.find('channel')
    if result is None:
        raise Failure('The remote feed is missing its channel.')
    return result


def add_episode(root, asset, title, now):
    parent = channel(root)
    guid = 'escape-pod-cast:asset-' + str(asset['id'])
    if any(item.findtext('guid') == guid for item in parent.findall('item')):
        return False
    item = ET.SubElement(parent, 'item')
    ET.SubElement(item, 'title').text = title
    ET.SubElement(item, 'guid', {'isPermaLink': 'false'}).text = guid
    ET.SubElement(item, 'pubDate').text = email.utils.format_datetime(now)
    ET.SubElement(item, 'description').text = 'Added from your Mac.'
    ET.SubElement(item, 'enclosure', {'url': asset['browser_download_url'],
                  'length': str(asset['size']), 'type': asset['content_type']})
    ET.SubElement(item, '{%s}explicit' % NS).text = 'false'
    return True


def remove_assets_from_feed(root, assets):
    urls = {asset['browser_download_url'] for asset in assets}
    parent, changed = channel(root), False
    for item in list(parent.findall('item')):
        enclosure = item.find('enclosure')
        if enclosure is not None and enclosure.get('url') in urls:
            parent.remove(item)
            changed = True
    return changed


def prepare_audio(source, directory):
    if not source.is_file() or source.stat().st_size == 0:
        raise Failure('Choose a nonempty audio file: ' + str(source))
    suffix = source.suffix.lower()
    # Probe the codec, not just its filename: M4A may contain Apple Lossless.
    probe = shutil.which('ffprobe')
    codec = ''
    if probe:
        result = subprocess.run([probe, '-v', 'error', '-select_streams', 'a:0',
                                 '-show_entries', 'stream=codec_name', '-of',
                                 'default=noprint_wrappers=1:nokey=1', str(source)],
                                capture_output=True, text=True)
        if result.returncode == 0:
            codec = result.stdout.strip()
    if not codec and sys.platform == 'darwin':
        result = subprocess.run(['/usr/bin/afinfo', str(source)],
                                capture_output=True, text=True)
        if result.returncode == 0:
            # afinfo prints codec names with or without quotes across macOS
            # versions, for example 'aac ' or aac (0x00000000).
            match = re.search(
                r'''^\s*Data format:[^\r\n]*?\bHz,\s*['"]?([A-Za-z0-9.]+)\s*['"]?\s*\(''',
                result.stdout, re.MULTILINE)
            codec = match.group(1) if match else ''
    if suffix == '.mp3' and codec in ('mp3', '.mp3'):
        return source, '.mp3', 'audio/mpeg'
    if suffix == '.m4a' and codec in ('aac', 'aach', 'aacl'):
        return source, '.m4a', 'audio/mp4'
    target = directory / 'episode.m4a'
    converter = shutil.which('ffmpeg')
    if converter:
        args = [converter, '-v', 'error', '-nostdin', '-y', '-i', str(source),
                '-map', '0:a:0', '-vn', '-c:a', 'aac', '-b:a', '128k',
                '-ac', '2', '-ar', '44100', '-movflags', '+faststart', str(target)]
    elif sys.platform == 'darwin':
        args = ['/usr/bin/afconvert', '-f', 'm4af', '-d', 'aac', '-b', '128000',
                str(source), str(target)]
    else:
        raise Failure('Install ffmpeg to convert this audio format.')
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode or not target.exists() or not target.stat().st_size:
        raise Failure('Could not convert ' + source.name +
                      '. For formats macOS cannot read, install ffmpeg and retry.')
    return target, '.m4a', 'audio/mp4'


def fingerprint(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_enclosure(url, size):
    # Use the public download URL, with no GitHub credential. Follow redirects
    # exactly as the podcast client will, and demand actual partial delivery.
    if sys.platform == 'darwin':
        status, _, headers = mac_transfer(url, 'HEAD', follow=True)
        if status != 200 or int(headers.get('content-length', '-1')) != size:
            raise Failure('Public audio HEAD response has the wrong file length.')
        status, payload, headers = mac_transfer(url, headers={'Range': 'bytes=0-0'},
                                               follow=True, max_size=1)
        if (status != 206 or headers.get('content-range') != 'bytes 0-0/%s' % size or
                len(payload) != 1):
            raise Failure('Public audio endpoint did not return a valid byte range.')
        return
    with urllib.request.urlopen(urllib.request.Request(url, method='HEAD'),
                                timeout=90) as response:
        if int(response.headers.get('Content-Length', '-1')) != size:
            raise Failure('Public audio HEAD response has the wrong file length.')
    req = urllib.request.Request(url, headers={'Range': 'bytes=0-0'})
    with urllib.request.urlopen(req, timeout=90) as response:
        if (response.status != 206 or
                response.headers.get('Content-Range') != 'bytes 0-0/%s' % size or
                len(response.read(2)) != 1):
            raise Failure('Public audio endpoint did not return a valid byte range.')


def publish(client, release, source, now):
    with tempfile.TemporaryDirectory() as directory:
        # Snapshot before conversion/upload so originals cannot change beneath
        # a streaming upload. Fail if a copy into the watched folder is active.
        before = source.stat()
        snapshot = Path(directory) / ('source' + source.suffix.lower())
        shutil.copyfile(source, snapshot)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise Failure('File is still changing. Retry after copying finishes.')
        media, suffix, mime = prepare_audio(snapshot, Path(directory))
        name = 'epc-' + fingerprint(snapshot) + suffix
        assets = client.assets(release)
        asset = next((a for a in assets if a['name'] == name), None)
        if asset and stamp(asset['created_at']) <= now - RETENTION:
            # A new drop of previously expired audio starts a new 14-day life.
            # Give its new asset a new GUID so Apple can recognize a new episode.
            root, sha = client.read_feed()
            if remove_assets_from_feed(root, [asset]):
                client.write_feed(root, sha)
            client.request('DELETE', '/releases/assets/%s' % asset['id'])
            asset = None
        if asset and asset.get('state') != 'uploaded':
            client.request('DELETE', '/releases/assets/%s' % asset['id'])
            asset = None
        if asset is None:
            if media.stat().st_size >= 2 * 1024 ** 3:
                raise Failure('The prepared episode must be smaller than 2 GiB.')
            asset = client.upload(release, media, name, mime)
        verify_enclosure(asset['browser_download_url'], asset['size'])
        # Read after upload. SHA-conditional write fails safely if another publisher
        # changes the feed. Retrying reuses the already completed audio upload.
        root, sha = client.read_feed()
        if add_episode(root, asset, source.stem, now):
            client.write_feed(root, sha)
        print('Published: ' + source.name, flush=True)


def cleanup(client, release, now):
    expired = [a for a in client.assets(release)
               if MEDIA_NAME.fullmatch(a['name']) and
               stamp(a['created_at']) <= now - RETENTION]
    if not expired:
        return
    root, sha = client.read_feed()
    if remove_assets_from_feed(root, expired):
        client.write_feed(root, sha)
    # Only delete after the feed update succeeds. A failed deletion is retried
    # next hour, including orphaned uploads that never reached the feed.
    for asset in expired:
        client.request('DELETE', '/releases/assets/%s' % asset['id'])
    print('Removed %s expired audio file(s).' % len(expired), flush=True)


def get_token(repo):
    result = subprocess.run(['/usr/bin/security', 'find-generic-password',
                             '-s', SERVICE, '-a', repo, '-w'],
                            capture_output=True, text=True)
    if result.returncode:
        raise Failure('GitHub credential unavailable. Run Install.command again.')
    return result.stdout.strip()


def setup(repo, token=None, progress=None):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise Failure('Repository must be owner/name.')
    if token is None:
        print('Use a GitHub fine-grained token restricted to ' + repo +
              ', with Contents, Pages, and Administration permissions: Read and write.\n'
              'Administration is needed only to enable/configure GitHub Pages.')
        token = getpass.getpass('Paste token (hidden): ').strip()
    if not re.fullmatch(r'[A-Za-z0-9_]+', token):
        raise Failure('Paste the GitHub token itself, without quotes or spaces.')
    report = progress or (lambda message: print(message, flush=True))
    report('Checking your GitHub connection…')
    client = GitHub(repo, token)
    metadata = client.request('GET', '')
    if metadata['private'] or metadata['default_branch'] != 'main':
        raise Failure('This version requires a public repository with main as default branch.')
    client.read_feed()
    report('Preparing temporary audio storage…')
    release = client.request('GET', '/releases/tags/audio', missing=True)
    if release is None:
        client.request('POST', '/releases', {
            'tag_name': 'audio', 'target_commitish': 'main',
            'name': 'Temporary podcast audio', 'body':
            'Escape Pod Cast audio. Files expire after 14 days.',
            'draft': False, 'prerelease': True})
    report('Preparing your podcast feed…')
    pages = client.request('GET', '/pages', missing=True)
    source = {'branch': 'main', 'path': '/docs'}
    if pages is None:
        pages = client.request('POST', '/pages', {'build_type': 'legacy', 'source': source})
    elif pages.get('source') != source or pages.get('build_type') != 'legacy':
        client.request('PUT', '/pages', {'build_type': 'legacy', 'source': source})
        pages = client.request('GET', '/pages')
    # security's interactive command input keeps the credential out of argv.
    # Tokens use a restricted alphabet, so quoting this command is unambiguous.
    report('Saving your connection in Mac Keychain…')
    command = 'add-generic-password -U -s "%s" -a "%s" -w "%s"\n' % (
        SERVICE, repo, token)
    result = subprocess.run(['/usr/bin/security', '-i'], input=command,
                            capture_output=True, text=True)
    if result.returncode or 'error' in result.stderr.lower():
        raise Failure('Could not store GitHub token in Keychain.')
    # Check retrieval instead of displaying the credential or security output.
    if get_token(repo) != token:
        raise Failure('Keychain verification failed.')
    HOME.mkdir(parents=True, exist_ok=True)
    feed_url = pages['html_url'].rstrip('/') + '/feed.xml'
    CONFIG.write_text(json.dumps({'repo': repo, 'feed_url': feed_url}, indent=2))
    (HOME / 'Feed URL.txt').write_text(feed_url + '\n')
    print('\nFollow this once in Apple Podcasts:\n' + feed_url +
          '\nPages may take a few minutes to publish. Enable automatic downloads.')
    return {'repo': repo, 'feed_url': feed_url}


@contextlib.contextmanager
def locked():
    HOME.mkdir(parents=True, exist_ok=True)
    with (HOME / 'publisher.lock').open('w') as lock:
        # Direct app drops wait; the folder monitor skips if another job is busy.
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def process_files(client, release, paths, now):
    failed = []
    for path in paths:
        try:
            publish(client, release, path, now)
        except (Failure, OSError, ValueError, ET.ParseError) as exc:
            print('Failed: %s: %s' % (path.name, exc), file=sys.stderr, flush=True)
            failed.append(path)
    return failed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', metavar='OWNER/REPO')
    parser.add_argument('--maintain', action='store_true')
    parser.add_argument('--notify', action='store_true')
    parser.add_argument('files', nargs='*', type=Path)
    args = parser.parse_args()
    if args.setup:
        setup(args.setup)
        return
    with locked():
        if not CONFIG.exists():
            raise Failure('Run Install.command first.')
        config = json.loads(CONFIG.read_text())
        inbox = HOME / 'Drop Audio Here'
        candidates = []
        if args.maintain:
            inbox.mkdir(exist_ok=True)
            for path in inbox.iterdir():
                if (path.is_file() and not path.name.startswith('.') and
                    path.suffix.lower() in ('.mp3', '.m4a', '.aac', '.wav', '.flac',
                                            '.ogg', '.opus', '.aif', '.aiff', '.mp4') and
                    dt.datetime.now().timestamp() - path.stat().st_mtime >= 60):
                    candidates.append(path)
            last = HOME / 'last-cleanup'
            if not candidates and last.exists() and not args.files:
                if dt.datetime.now().timestamp() - last.stat().st_mtime < 3600:
                    return
        client = GitHub(config['repo'], get_token(config['repo']))
        release = client.request('GET', '/releases/tags/audio')
        now = dt.datetime.now(dt.timezone.utc)
        failed = process_files(client, release, args.files, now)
        if args.maintain:
            done = inbox / 'Published'
            done.mkdir(parents=True, exist_ok=True)
            errors = process_files(client, release, candidates, now)
            failed.extend(errors)
            for path in candidates:
                if path not in errors:
                    destination = done / path.name
                    if destination.exists():
                        destination = done / (path.stem + '-' + fingerprint(path)[:12] + path.suffix)
                    shutil.move(str(path), str(destination))
        cleanup(client, release, now)
        (HOME / 'last-cleanup').touch()
        if failed:
            raise Failure('%s file(s) failed. Successful files are already published. '
                          'Retry failures; see Status.log for details.' % len(failed))


if __name__ == '__main__':
    try:
        main()
        if '--notify' in sys.argv:
            subprocess.run(['/usr/bin/osascript', '-e',
                            'display dialog "Audio published. Apple Podcasts will pick it up '
                            'when it refreshes your show." buttons {"OK"} '
                            'default button "OK" with title "Escape Pod Cast"'])
    except (Failure, OSError, ValueError, ET.ParseError) as exc:
        print(str(exc), file=sys.stderr)
        if '--notify' in sys.argv:
            subprocess.run(['/usr/bin/osascript', '-e',
                            'display dialog "Publishing needs attention. Open Status.log '
                            'in your Escape Pod Cast folder for details, then retry the file." '
                            'buttons {"OK"} default button "OK" '
                            'with title "Escape Pod Cast"'])
        sys.exit(1)
