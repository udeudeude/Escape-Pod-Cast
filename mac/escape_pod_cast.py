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
import platform
from pathlib import Path
import plistlib
import re
import secrets
import signal
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

HOME = Path.home() / 'Library/Application Support/Escape Pod Cast'
CONFIG = HOME / 'config.json'
SERVICE = 'Escape Pod Cast GitHub'
NS = 'http://www.itunes.com/dtds/podcast-1.0.dtd'
ET.register_namespace('itunes', NS)
RETENTION = dt.timedelta(days=14)
MEDIA_NAME = re.compile(r'^epc-[0-9a-f]{64}\.(mp3|m4a)$')
AUDIO_TYPES = ('.mp3', '.m4a', '.aac', '.wav', '.flac', '.ogg', '.opus', '.aif', '.aiff', '.mp4')
RETRY_DELAYS = (30, 120, 300)
FEED_SETTINGS = 'escape-pod-cast.json'
LEGACY_FEED = 'docs/feed.xml'
FEED_PATH = re.compile(r'^docs/feeds/[0-9a-f]{48}/feed\.xml$')
SITE_INDEX = '''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta name="robots" content="noindex, nofollow">
<title>Escape Pod Cast</title><h1>Escape Pod Cast</h1>
<p>Use the Mac app's Copy podcast link action to follow your show.</p>
<p>The feed has a random address. The repository and audio are publicly accessible.</p>
</html>
'''


class Failure(RuntimeError):
    pass


class NetworkFailure(Failure):
    pass


class Aborted(Failure):
    pass


def abort_path(job_id):
    return job_path(job_id).with_suffix('.abort')


def check_abort():
    if CURRENT_JOB and CURRENT_JOB.get('abortable', True) and abort_path(CURRENT_JOB['id']).exists():
        raise Aborted('Aborted. Your original audio is kept.')


def request_abort(job_id, delete=False):
    # Serialize the request with the worker's final publication boundary.
    with intake_lock():
        job = load_job(job_id)
        if job['state'] != 'running':
            raise Failure('This item is no longer running. Select Delete to remove it.')
        if not job.get('abortable', True):
            raise Failure('The feed update is finishing. Let it finish, then delete the episode.')
        abort_path(job_id).write_text('delete' if delete else 'abort')


def publication_boundary():
    if CURRENT_JOB is None:
        return
    with intake_lock():
        check_abort()
        job_progress('Adding the episode to your podcast', abortable=False)


def process_command(args, progress_file=None, progress_kind=None, **options):
    """Interrupt only our child process group, never the publisher mid-transaction."""
    if CURRENT_JOB is None:
        return subprocess.run(args, **options)
    check_abort()
    timeout = options.pop('timeout', None)
    input_value = options.pop('input', None)
    capture = options.pop('capture_output', False)
    if capture:
        options.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if input_value is not None:
        options['stdin'] = subprocess.PIPE
    started = time.monotonic()
    child = subprocess.Popen(args, start_new_session=True, **options)
    try:
        while True:
            check_abort()
            if timeout is not None and time.monotonic() - started > timeout:
                raise subprocess.TimeoutExpired(args, timeout)
            if progress_file and progress_file.exists():
                with progress_file.open('rb') as stream:
                    stream.seek(max(0, progress_file.stat().st_size - 4096))
                    parse_transfer_progress(stream.read().decode('utf-8', errors='replace'), progress_kind)
            try:
                stdout, stderr = child.communicate(input=input_value, timeout=0.2)
                return subprocess.CompletedProcess(args, child.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                input_value = None
    finally:
        if child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.communicate()


def parse_transfer_progress(text, kind):
    if kind == 'youtube':
        matches = re.findall(r'EPC_PROGRESS\s+([0-9.]+)%', text)
    else:
        # curl's standard meter: %Total Total %Received Received %Xferd Uploaded.
        matches = []
        for line in re.split(r'[\r\n]', text):
            fields = line.split()
            if len(fields) >= 12 and fields[0].isdigit() and fields[4].isdigit():
                matches.append(fields[4])
    if matches and CURRENT_JOB:
        value = min(100, max(0, float(matches[-1])))
        if CURRENT_JOB.get('percent') != value:
            job_progress(CURRENT_JOB['stage'], percent=value)


def queue_paused():
    return (HOME / 'queue-paused').exists()


def pause_queue(paused):
    HOME.mkdir(parents=True, exist_ok=True)
    if paused:
        (HOME / 'queue-paused').touch()
    else:
        (HOME / 'queue-paused').unlink(missing_ok=True)


def ready_job(job, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    return (job['state'] == 'queued' and not queue_paused() and
            (not job.get('next_attempt') or stamp(job['next_attempt']) <= now))


def episode_status(job, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    state, publication = job['state'], job.get('publication')
    if state == 'queued':
        if queue_paused():
            return 'Paused'
        if job.get('next_attempt'):
            seconds = max(0, int((stamp(job['next_attempt']) - now).total_seconds()))
            return 'Retry in %s:%02d' % divmod(seconds, 60)
        return 'Waiting'
    if state != 'done':
        return {'running': 'Publishing…', 'failed': 'Needs attention', 'cancelled': 'Removed'}[state]
    if publication in ('expired', 'removed', 'removal_pending'):
        return {'expired': 'Expired', 'removed': 'Removed from podcast', 'removal_pending': 'Removal pending'}[publication]
    if job.get('expires_at') and stamp(job['expires_at']) <= now:
        return 'Expiry due'
    if publication == 'feed_pending':
        return 'Feed updating'
    if publication == 'available':
        hours = max(1, int((stamp(job['expires_at']) - now).total_seconds() / 3600)) if job.get('expires_at') else None
        remaining = ('%sd' % (hours//24)) if hours and hours >= 24 else '%sh' % hours if hours else ''
        return 'Available' + (' · expires in ' + remaining if remaining else '')
    return 'Published · unverified' if job['kind'] in ('file', 'youtube') else 'Done'


def transient_error(exc):
    if isinstance(exc, NetworkFailure):
        return not any(word in str(exc).lower() for word in ('certificate', 'proxy', 'byte range'))
    return isinstance(exc, (TimeoutError, ConnectionError, urllib.error.URLError))


def redact(value):
    value = re.sub(r'\b(?:github_pat_[A-Za-z0-9_]+|gh[pousr]_[A-Za-z0-9_]+)\b', '<TOKEN REDACTED>', str(value))
    value = re.sub(r'(?i)(authorization["\s:=]+(?:bearer\s+)?)[^\s,\"\}]+', r'\1<REDACTED>', value)
    value = re.sub(r'/feeds/[0-9a-f]{48}/', '/feeds/<ADDRESS REDACTED>/', value)
    return value.replace(str(HOME.resolve()), '<APP DATA>').replace(str(HOME), '<APP DATA>').replace(str(Path.home()), '<HOME>')


def diagnostic_report():
    report = {'python': platform.python_version(), 'macOS': platform.mac_ver()[0],
              'machine': platform.machine(), 'queue_paused': queue_paused(),
              'connected': CONFIG.exists(), 'jobs': []}
    for job in list_jobs():
        report['jobs'].append({key: redact(job.get(key, '')) for key in
                              ('kind', 'state', 'stage', 'attempts', 'auto_retries', 'next_attempt', 'publication', 'error')})
    log = HOME / 'Status.log'
    if log.exists():
        with log.open('rb') as stream:
            stream.seek(max(0, log.stat().st_size - 50000))
            report['log_tail'] = redact(stream.read().decode('utf-8', errors='replace'))
    return report


def audio_command(args, timeout=900):
    try:
        return process_command(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Failure('The audio tool timed out. Your original is kept; retry or try a compatible audio copy.') from None


def fail_job(job, exc):
    count = job.get('auto_retries', 0)
    if transient_error(exc) and count < len(RETRY_DELAYS):
        delay = RETRY_DELAYS[count]
        job.update(state='queued', stage='Connection interrupted — retry scheduled', pid=None,
                   error=str(exc), help='The app will retry automatically. Pause queue to postpone it.',
                   auto_retries=count+1, next_attempt=(dt.datetime.now(dt.timezone.utc) +
                                                     dt.timedelta(seconds=delay)).isoformat())
    else:
        job.update(state='failed', stage='Needs attention', pid=None,
                   error=str(exc), help=recovery_hint(str(exc)), next_attempt=None)


def remember_episode(asset, now):
    job_progress('Waiting for the public feed', publication='feed_pending',
                 asset_id=asset['id'], guid='escape-pod-cast:asset-' + str(asset['id']),
                 enclosure=asset['browser_download_url'], published_at=now.isoformat(),
                 expires_at=(stamp(asset['created_at']) + RETENTION).isoformat())


def mark_asset_removed(asset_id, reason):
    for job in list_jobs():
        if job.get('asset_id') == asset_id and job['state'] == 'done':
            with job_lock(job['id'], blocking=False) as acquired:
                if acquired:
                    job = load_job(job['id'])
                    job.update(publication=reason, stage='Expired' if reason == 'expired' else 'Removed from podcast')
                    save_job(job)


def confirm_publications():
    """One bounded public RSS check; it does not claim an iPhone downloaded it."""
    pending = [job for job in list_jobs() if job['state'] == 'done' and job.get('publication') == 'feed_pending']
    if not pending or not CONFIG.exists():
        return
    config = json.loads(CONFIG.read_text())
    if not isinstance(config.get('feed_url'), str) or not config['feed_url'].startswith('https://'):
        return
    try:
        if sys.platform == 'darwin':
            status, data, _ = mac_transfer(config['feed_url'], follow=True, max_time=20, max_size=4*1024**2)
            if status != 200:
                return
        else:
            with urllib.request.urlopen(config['feed_url'], timeout=20) as response:
                data = response.read(4*1024**2 + 1)
            if len(data) > 4*1024**2:
                return
        root = ET.fromstring(data)
        items = {item.findtext('guid'): item for item in channel(root).findall('item')}
    except (Failure, OSError, ValueError, ET.ParseError):
        return  # A failed verification leaves honest Feed updating status.
    for job in pending:
        item = items.get(job.get('guid'))
        enclosure = item.find('enclosure') if item is not None else None
        if enclosure is not None and enclosure.get('url') == job.get('enclosure'):
            with job_lock(job['id'], blocking=False) as acquired:
                if acquired:
                    current = load_job(job['id'])
                    if current.get('publication') == 'feed_pending' and current['state'] == 'done':
                        current.update(publication='available', stage='Available in the public feed',
                                       verified_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                                       message='Available to podcast apps. Apple controls when your iPhone refreshes and downloads it.')
                        save_job(current)


def edit_job(job_id, title, description):
    with job_lock(job_id, blocking=False) as acquired:
        if not acquired:
            raise Failure('This episode is publishing. Edit waiting or failed items.')
        job = load_job(job_id)
        if job['state'] not in ('queued', 'failed') or job['kind'] not in ('file', 'youtube'):
            raise Failure('Edit an audio item while it is waiting or failed.')
        title, description = title.strip(), description.strip()
        if not title or len(title) > 1000 or len(description) > 10000:
            raise Failure('Use a title of 1–1000 characters and a description of at most 10,000 characters.')
        for value in (title, description):
            if any(ord(c) < 32 and c not in '\n\r\t' or 0xd800 <= ord(c) <= 0xdfff for c in value):
                raise Failure('The episode text contains an unsupported control character.')
        job.update(title=title, label=title, description=description)
        save_job(job)


def move_job(job_id, direction):
    with intake_lock():
        waiting = [job for job in list_jobs() if job['state'] == 'queued']
        keys = [job['id'] for job in waiting]
        if job_id not in keys:
            raise Failure('Only waiting items can be reordered.')
        index = keys.index(job_id)
        other = max(0, min(len(keys)-1, index + direction))
        waiting[index], waiting[other] = waiting[other], waiting[index]
        slots = sorted(job.get('order', job['created']) for job in waiting)
        # The publisher uses the same intake lock when claiming the next job.
        for job, slot in zip(waiting, slots):
            with job_lock(job['id'], blocking=False) as acquired:
                if acquired:
                    current = load_job(job['id'])
                    if current['state'] == 'queued':
                        current['order'] = slot
                        save_job(current)


def delete_episode(job_id):
    with locked():
        job = load_job(job_id)
        if job['state'] != 'done' or not job.get('asset_id') or not job.get('enclosure'):
            raise Failure('Select an episode published by this version of the app.')
        config = json.loads(CONFIG.read_text())
        client = GitHub(config['repo'], get_token(config['repo']))
        root, sha = client.read_feed()
        asset = {'id': job['asset_id'], 'browser_download_url': job['enclosure']}
        if remove_assets_from_feed(root, [asset]):
            client.write_feed(root, sha)
        job.update(publication='removal_pending', stage='Removing published audio')
        save_job(job)
        client.request('DELETE', '/releases/assets/%s' % job['asset_id'], missing=True)
        mark_asset_removed(job['asset_id'], 'removed')


@contextlib.contextmanager
def intake_lock():
    HOME.mkdir(parents=True, exist_ok=True)
    with (HOME / 'intake.lock').open('w') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


CURRENT_JOB = None


def activity_folder():
    return HOME / 'Activity'


def job_path(job_id):
    if not re.fullmatch(r'[0-9a-f]{32}', job_id):
        raise Failure('This publishing task is invalid. Add the item again.')
    return activity_folder() / (job_id + '.json')


def save_job(job):
    path = job_path(job['id'])
    path.parent.mkdir(parents=True, exist_ok=True)
    job['updated'] = dt.datetime.now(dt.timezone.utc).isoformat()
    # Readers always see either the previous or the complete new state.
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as output:
        temp = Path(output.name)
        json.dump(job, output, ensure_ascii=True)
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def load_job(job_id):
    job = json.loads(job_path(job_id).read_text())
    if (job.get('id') != job_id or job.get('kind') not in ('file', 'youtube', 'tools', 'check') or
            job.get('state') not in ('queued', 'running', 'done', 'failed', 'cancelled') or
            not all(isinstance(job.get(key), str) for key in ('source', 'label', 'created', 'stage'))):
        raise Failure('This publishing task is invalid. Add the item again.')
    return job


def list_jobs():
    folder = activity_folder()
    if not folder.exists():
        return []
    jobs = []
    for path in folder.glob('*.json'):
        try:
            jobs.append(load_job(path.stem))
        except (Failure, OSError, ValueError, TypeError, AttributeError):
            continue
    return sorted(jobs, key=lambda job: job.get('order', job.get('created', '')))


def create_job(kind, source='', allow_invalid_link=False):
    if kind == 'youtube':
        source, video = youtube_url(source)
        label = 'YouTube · ' + video
    elif kind == 'file':
        source = str(Path(source).expanduser().resolve())
        if not Path(source).is_file():
            raise Failure('That file is no longer available. Choose it again.')
        label = Path(source).name
        if Path(source).suffix.lower() not in AUDIO_TYPES + LINK_TYPES:
            raise Failure('Choose a supported audio track or a saved YouTube video link.')
    elif kind in ('tools', 'check'):
        label = 'Set up YouTube' if kind == 'tools' else 'Check connection'
    else:
        raise Failure('Unknown app action.')
    problem = None
    key = [kind, source]
    if kind == 'file' and Path(source).suffix.lower() in LINK_TYPES:
        try:
            key = ['youtube', link_file(Path(source))]
        except Failure as exc:
            if not allow_invalid_link:
                raise
            problem = exc
    with intake_lock():
        for previous in list_jobs():
            previous_key = previous.get('intake_key', [previous['kind'], previous['source']])
            if previous_key == key and previous['state'] in ('queued', 'running'):
                return previous
        job = {'id': uuid.uuid4().hex, 'kind': kind, 'source': source, 'label': label,
           'created': dt.datetime.now(dt.timezone.utc).isoformat(), 'state': 'queued',
           'stage': 'Waiting to start', 'error': '', 'help': '', 'attempts': 0, 'pid': None,
           'intake_key': key}
        if problem:
            fail_job(job, problem)
        save_job(job)
    return job


def job_progress(stage, **values):
    if CURRENT_JOB is not None:
        check_abort()
        if stage != CURRENT_JOB.get('stage'):
            CURRENT_JOB['percent'] = None
        CURRENT_JOB.update(stage=stage, **values)
        save_job(CURRENT_JOB)


def recovery_hint(message):
    text = message.lower()
    if any(word in text for word in ('401', '403', 'credential', 'keychain', 'token expired')):
        return 'Open Settings → Reconnect GitHub. Reuse your saved connection if it still works.'
    if any(word in text for word in ('network', 'connection', 'timed out', 'server could not')):
        return 'Check your internet connection, then click Retry. You do not need a new GitHub token.'
    if 'youtube' in text or 'video' in text:
        return 'For a finished public video, update the YouTube helpers in Settings, then retry. Restricted videos may remain unavailable.'
    if 'convert' in text or 'audio format' in text:
        return 'Try an MP3 or AAC-encoded M4A copy. Keep the original; renaming its extension will not convert it.'
    if 'no such file' in text or 'file is no longer' in text:
        return 'Restore the original file to its location, or use Add audio to choose it again.'
    if 'concurrent' in text or 'sha' in text:
        return 'Another Mac may have updated this feed. Click Retry; completed uploads are reused.'
    return 'Click Retry when ready. Your original is untouched and completed uploads are reused. Details are available below.'


@contextlib.contextmanager
def job_lock(job_id, blocking=True):
    path = job_path(job_id).with_suffix('.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        yield True


def recover_jobs():
    """A closed window does not cancel work; only recover genuinely dead workers."""
    for job in list_jobs():
        if job.get('state') != 'running':
            continue
        with job_lock(job['id'], blocking=False) as acquired:
            if not acquired:
                continue
            job = load_job(job['id'])
            if job['state'] != 'running':
                continue
            try:
                pid = int(job['pid'])
                if pid <= 0:
                    raise ValueError()
                os.kill(pid, 0)
            except PermissionError:
                continue
            except (ProcessLookupError, ValueError, TypeError):
                job.update(state='failed', stage='Interrupted', pid=None,
                           error='Publishing stopped before a completion result was saved.',
                           help='Click Retry. A completed audio upload will be reused.')
                save_job(job)


def retry_job(job_id):
    # A failed job is no longer owned by a live publisher. Queue it without
    # blocking the window behind an unrelated long upload.
    with job_lock(job_id, blocking=False) as acquired:
        if not acquired:
            raise Failure('This task is finishing. Try Retry again in a moment.')
        job = load_job(job_id)
        if job['state'] not in ('failed', 'cancelled'):
            raise Failure('Only a failed or aborted task needs a retry.')
        job.update(state='queued', stage='Waiting to retry', error='', help='', pid=None,
                   next_attempt=None, auto_retries=0, percent=None, abortable=True)
        abort_path(job_id).unlink(missing_ok=True)
        save_job(job)
    return job


def cancel_job(job_id, delete=False):
    with job_lock(job_id, blocking=False) as acquired:
        if not acquired:
            raise Failure('This item is already publishing. Let it finish; queued items can be removed.')
        job = load_job(job_id)
        if job['state'] not in ('queued', 'failed', 'cancelled'):
            raise Failure('Only waiting or failed items can be removed from the queue.')
        finish_abort(job)
        if delete:
            job_path(job_id).unlink(missing_ok=True)


def finish_abort(job):
    job_id = job['id']
    source = Path(job['source'])
    message = 'Aborted / removed from queue. Temporary work is discarded; your original audio is kept.'
    if job.get('origin') == 'folder' and source.parent.resolve() == (HOME / 'Drop Audio Here').resolve() and source.exists():
        hold = source.parent / 'Not Published'
        hold.mkdir(exist_ok=True)
        destination = hold / source.name
        if destination.exists():
            destination = hold / (source.stem + '-' + job_id[:12] + source.suffix)
        shutil.move(str(source), str(destination))
        job['source'] = str(destination.resolve())
        message = 'The original is kept in the drop folder’s Not Published subfolder. Retry or move it back to try again.'
    job.update(state='cancelled', stage='Aborted / removed', error='', help='', pid=None,
               message=message, percent=None)
    save_job(job)


def archive_source(path):
    done = HOME / 'Drop Audio Here' / 'Published'
    done.mkdir(parents=True, exist_ok=True)
    destination = done / path.name
    if destination.exists():
        destination = done / (path.stem + '-' + fingerprint(path)[:12] + path.suffix)
    shutil.move(str(path), str(destination))
    return destination


@contextlib.contextmanager
def record_folder_file(path):
    global CURRENT_JOB
    source = str(path.resolve())
    previous = next((job for job in reversed(list_jobs()) if job.get('source') == source and
                     job.get('origin') == 'folder' and job['state'] in ('failed', 'queued')), None)
    job = previous or create_job('file', source)
    with job_lock(job['id']):
        job.update(origin='folder', state='running', pid=os.getpid(), stage='Starting', error='', help='',
                   started=dt.datetime.now(dt.timezone.utc).isoformat(),
                   attempts=job.get('attempts', 0) + 1)
        CURRENT_JOB = job
        save_job(job)
        try:
            yield
            job.update(state='done', stage='Published', pid=None,
                       message='Published. The original moves into the drop folder’s Published subfolder.')
        except (Failure, OSError, ValueError, ET.ParseError) as exc:
            fail_job(job, exc)
            raise
        finally:
            save_job(job)
            CURRENT_JOB = None


def perform_job(job):
    if job['kind'] == 'tools':
        install_youtube_tools()
        return 'YouTube is ready. Paste a video link to add an episode.'
    if not CONFIG.exists():
        raise Failure('Your connection is not set up. Open Settings → Reconnect GitHub.')
    config = json.loads(CONFIG.read_text())
    job_progress('Connecting to GitHub')
    client = GitHub(config['repo'], get_token(config['repo']))
    if job['kind'] == 'check':
        client.request('GET', '')
        client.request('GET', '/releases/tags/audio')
        job_progress('Checking your podcast address')
        root = ET.fromstring(public_bytes(config['feed_url']))
        if root.find('channel') is None:
            raise Failure('The podcast address did not return a readable feed.')
        return 'GitHub and your podcast feed are reachable. Apple controls refresh timing.'
    release = client.request('GET', '/releases/tags/audio')
    now = dt.datetime.now(dt.timezone.utc)
    if job['kind'] == 'youtube':
        publish_youtube(client, release, job['source'], now)
    else:
        source = Path(job['source'])
        if source.suffix.lower() in LINK_TYPES:
            publish_youtube(client, release, link_file(source), now, prompt=job.get('origin') != 'folder')
        else:
            publish(client, release, source, now)
        if job.get('origin') == 'folder' and source.parent.resolve() == (HOME / 'Drop Audio Here').resolve():
            job_progress('Original archived', original_path=str(archive_source(source)))
    return 'Audio uploaded and feed committed. Waiting for GitHub Pages; Apple controls subsequent downloads.'


def run_job(job_id, blocking=True):
    global CURRENT_JOB
    with locked(blocking=blocking) as acquired:
        if not acquired:
            return
        with job_lock(job_id):
            job = load_job(job_id)
            # The GUI and folder monitor can pick the same queued job. Claim only here.
            if not ready_job(job):
                return
            job.update(state='running', pid=os.getpid(), stage='Starting', error='', help='',
                       abortable=True, percent=None,
                       started=dt.datetime.now(dt.timezone.utc).isoformat(),
                       attempts=job.get('attempts', 0) + 1)
            CURRENT_JOB = job
            save_job(job)
            try:
                result = perform_job(job)
                job.update(state='done', stage='Ready' if job['kind'] in ('tools', 'check') else
                           'Feed updating' if job.get('publication') == 'feed_pending' else 'Published',
                           message=result, pid=None)
            except Aborted:
                finish_abort(job)
            except (Failure, OSError, ValueError, TypeError, KeyError, ET.ParseError) as exc:
                message = str(exc)
                print('Failed: %s: %s' % (job['label'], message), file=sys.stderr, flush=True)
                if job.get('abortable', True) and abort_path(job_id).exists():
                    finish_abort(job)
                else:
                    fail_job(job, exc)
            finally:
                save_job(job)
                marker = abort_path(job_id)
                if job['state'] == 'cancelled' and marker.exists() and marker.read_text() == 'delete':
                    job_path(job_id).unlink(missing_ok=True)
                marker.unlink(missing_ok=True)
                CURRENT_JOB = None
    confirm_publications()


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
        if upload is not None and CURRENT_JOB is not None:
            args.remove('--silent')
            meter = folder / 'progress'
            with meter.open('w') as progress:
                result = process_command(args, input=config, stdout=subprocess.PIPE, stderr=progress,
                                         text=True, progress_file=meter, progress_kind='curl')
        else:
            result = process_command(args, input=config, capture_output=True, text=True)
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
        self.feed_path = None

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
                if status in (408, 429) or status >= 500:
                    raise NetworkFailure('GitHub is temporarily unavailable (%s). The app will retry.' % status)
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
            if exc.code in (408, 429) or exc.code >= 500:
                raise NetworkFailure('GitHub is temporarily unavailable (%s). The app will retry.' % exc.code) from None
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

    def upload(self, release, path, name, mime, label=None):
        job_progress('Uploading audio', percent=0)
        # Stream from disk; do not hold a potentially 2 GiB episode in memory.
        url = urllib.parse.urlsplit(release['upload_url'].split('{')[0])
        if url.scheme != 'https' or url.hostname != 'uploads.github.com':
            raise Failure('Unexpected GitHub upload endpoint.')
        query = urllib.parse.urlencode({'name': name, **({'label': label} if label else {})})
        if sys.platform == 'darwin':
            headers = self.headers()
            headers['Content-Type'] = mime
            status, raw, _ = mac_transfer(release['upload_url'].split('{')[0] +
                                         '?' + query, 'POST', headers,
                                         upload=path, max_time=900)
            if status != 201:
                if status in (408, 429) or status >= 500:
                    raise NetworkFailure('The upload service is temporarily unavailable (%s).' % status)
                raise Failure('Audio upload failed (%s). Retry the original file; '
                              'completed uploads are reused.' % status)
            return json.loads(raw)
        connection = http.client.HTTPSConnection(url.hostname, timeout=900)
        headers = self.headers()
        headers.update({'Content-Type': mime, 'Content-Length': str(path.stat().st_size)})
        try:
            with path.open('rb') as stream:
                connection.request('POST', url.path + '?' + query,
                                   body=stream, headers=headers)
                response = connection.getresponse()
                raw = response.read()
                if response.status != 201:
                    if response.status in (408, 429) or response.status >= 500:
                        raise NetworkFailure('The upload service is temporarily unavailable (%s).' % response.status)
                    raise Failure('Audio upload failed (%s). Retry the original file; '
                                  'completed uploads are reused.' % response.status)
                return json.loads(raw)
        finally:
            connection.close()

    def content(self, path, ref='main', missing=False):
        return self.request('GET', '/contents/' + urllib.parse.quote(path, safe='/') +
                            '?ref=' + urllib.parse.quote(ref, safe=''), missing=missing)

    def feed_setting(self, item):
        if item is None:
            return None
        settings = json.loads(base64.b64decode(item['content']))
        if settings.get('repo', '').lower() != self.repo.lower():
            return None  # A fork must create its own feed, not use its parent's.
        path = settings.get('feed_path', '')
        if settings.get('version') != 1 or not FEED_PATH.fullmatch(path):
            raise Failure('The repository feed settings are invalid. Restore them before publishing.')
        return path

    def read_feed(self):
        if self.feed_path is None:
            settings = self.content(FEED_SETTINGS, missing=True)
            self.feed_path = self.feed_setting(settings) or LEGACY_FEED
        item = self.content(self.feed_path)
        return ET.fromstring(base64.b64decode(item['content'])), item['sha']

    def write_feed(self, root, sha):
        content = ET.tostring(root, encoding='utf-8', xml_declaration=True)
        if self.feed_path is None:
            self.read_feed()
        return self.request('PUT', '/contents/' + self.feed_path, {
            'message': 'Update personal podcast episodes', 'branch': 'main',
            'sha': sha, 'content': base64.b64encode(content).decode()})

    def initialize_feed(self):
        # Migrate the feed and remove its predictable route in one commit.
        # A concurrent publish prevents the branch move; retry from a fresh
        # snapshot rather than overwriting an episode or losing the old feed.
        parent = self.request('GET', '/git/ref/heads/main')['object']['sha']
        settings_item = self.content(FEED_SETTINGS, ref=parent, missing=True)
        existing = self.feed_setting(settings_item)
        if existing:
            self.feed_path = existing
            self.read_feed()  # Preserve the address; fail if its feed is missing.
            return existing
        legacy = self.content(LEGACY_FEED, ref=parent, missing=True)
        inherited_path = None
        inherited = None
        if settings_item:
            inherited_path = json.loads(base64.b64decode(settings_item['content'])).get('feed_path', '')
            if FEED_PATH.fullmatch(inherited_path):
                inherited = self.content(inherited_path, ref=parent, missing=True)
        source = legacy or inherited
        root = (ET.fromstring(base64.b64decode(source['content'])) if source else new_feed())
        # Forks copy files and history, not Release assets. Keep only episodes
        # hosted by the selected repository, never someone else's copied show.
        own_audio = 'https://github.com/' + self.repo + '/releases/download/'
        for item in list(channel(root).findall('item')):
            enclosure = item.find('enclosure')
            if enclosure is None or not enclosure.get('url', '').lower().startswith(own_audio.lower()):
                channel(root).remove(item)
        channel(root).find('link').text = 'https://github.com/' + self.repo
        path = 'docs/feeds/' + secrets.token_hex(24) + '/feed.xml'
        settings = {'version': 1, 'repo': self.repo, 'feed_path': path}
        entries = [{'path': path, 'mode': '100644', 'type': 'blob',
                    'content': ET.tostring(root, encoding='unicode', xml_declaration=True)},
                   {'path': FEED_SETTINGS, 'mode': '100644', 'type': 'blob',
                    'content': json.dumps(settings, indent=2) + '\n'},
                   {'path': 'docs/index.html', 'mode': '100644', 'type': 'blob',
                    'content': SITE_INDEX}]
        for old_path, old_item in ((LEGACY_FEED, legacy), (inherited_path, inherited)):
            if old_item:
                entries.append({'path': old_path, 'mode': '100644', 'type': 'blob', 'sha': None})
        commit = self.request('GET', '/git/commits/' + parent)
        tree = self.request('POST', '/git/trees', {'base_tree': commit['tree']['sha'], 'tree': entries})
        created = self.request('POST', '/git/commits', {
            'message': 'Give this podcast its own random feed address',
            'tree': tree['sha'], 'parents': [parent]})
        self.request('PATCH', '/git/refs/heads/main', {'sha': created['sha'], 'force': False})
        self.feed_path = path
        return path


def stamp(value):
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00'))


def channel(root):
    result = root.find('channel')
    if result is None:
        raise Failure('The remote feed is missing its channel.')
    return result


def new_feed():
    root = ET.Element('rss', {'version': '2.0'})
    parent = ET.SubElement(root, 'channel')
    for name, value in (
            ('title', 'Escape Pod Cast'), ('link', 'https://github.com/'),
            ('description', 'Audio dropped from my Mac. Remote audio expires after 14 days.'),
            ('language', 'en-us'), ('{%s}author' % NS, 'Escape Pod Cast'),
            ('{%s}explicit' % NS, 'false'), ('{%s}block' % NS, 'Yes'),
            ('{%s}type' % NS, 'episodic')):
        ET.SubElement(parent, name).text = value
    return root


def add_episode(root, asset, title, now, description=None):
    parent = channel(root)
    guid = 'escape-pod-cast:asset-' + str(asset['id'])
    if any(item.findtext('guid') == guid for item in parent.findall('item')):
        return False
    item = ET.SubElement(parent, 'item')
    ET.SubElement(item, 'title').text = title
    ET.SubElement(item, 'guid', {'isPermaLink': 'false'}).text = guid
    ET.SubElement(item, 'pubDate').text = email.utils.format_datetime(now)
    ET.SubElement(item, 'description').text = description or 'Added from your Mac.'
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
    job_progress('Checking the audio format')
    if not source.is_file() or source.stat().st_size == 0:
        raise Failure('Choose a nonempty audio file: ' + str(source))
    suffix = source.suffix.lower()
    # Probe the codec, not just its filename: M4A may contain Apple Lossless.
    probe = shutil.which('ffprobe')
    codec = ''
    if probe:
        result = audio_command([probe, '-v', 'error', '-select_streams', 'a:0',
                                 '-show_entries', 'stream=codec_name', '-of',
                                 'default=noprint_wrappers=1:nokey=1', str(source)],
                                timeout=30)
        if result.returncode == 0:
            codec = result.stdout.strip()
    if not codec and sys.platform == 'darwin':
        result = audio_command(['/usr/bin/afinfo', str(source)], timeout=30)
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
    job_progress('Converting audio for Apple Podcasts')
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
    result = audio_command(args)
    if result.returncode or not target.exists() or not target.stat().st_size:
        detail = redact((result.stderr or result.stdout or 'The converter did not produce playable audio.').strip()[-2000:])
        raise Failure('Could not convert ' + source.name + '. ' + detail +
                      '\nTry a compatible MP3/AAC copy, or install ffmpeg for formats macOS cannot read.')
    return target, '.m4a', 'audio/mp4'


def fingerprint(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            check_abort()
            digest.update(chunk)
    return digest.hexdigest()


def copy_audio(source, target):
    size = source.stat().st_size
    job_progress('Copying audio', percent=0)
    copied = 0
    with source.open('rb') as original, target.open('wb') as output:
        for chunk in iter(lambda: original.read(1024 * 1024), b''):
            check_abort()
            output.write(chunk)
            copied += len(chunk)
            percent = min(100, int(copied * 100 / max(1, size)))
            if (CURRENT_JOB or {}).get('percent') != percent:
                job_progress('Copying audio', percent=percent)


def verify_enclosure(url, size):
    job_progress('Checking the uploaded audio can be played')
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


def publish(client, release, source, now, title=None, identity=None):
    title = (CURRENT_JOB or {}).get('title') or title
    job_progress('Preparing audio', label=title or source.name)
    with tempfile.TemporaryDirectory() as directory:
        # Snapshot before conversion/upload so originals cannot change beneath
        # a streaming upload. Fail if a copy into the watched folder is active.
        before = source.stat()
        snapshot = Path(directory) / ('source' + source.suffix.lower())
        copy_audio(source, snapshot)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise Failure('File is still changing. Retry after copying finishes.')
        media, suffix, mime = prepare_audio(snapshot, Path(directory))
        name = 'epc-' + (identity or fingerprint(snapshot)) + suffix
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
            if identity and title:
                asset = client.upload(release, media, name, mime, label=title[:255])
            else:
                asset = client.upload(release, media, name, mime)
        verify_enclosure(asset['browser_download_url'], asset['size'])
        # Read after upload. SHA-conditional write fails safely if another publisher
        # changes the feed. Retrying reuses the already completed audio upload.
        publication_boundary()
        root, sha = client.read_feed()
        if add_episode(root, asset, title or source.stem, now, (CURRENT_JOB or {}).get('description')):
            client.write_feed(root, sha)
        remember_episode(asset, now)
        print('Published: ' + (title or source.name), flush=True)


LINK_TYPES = ('.webloc', '.url', '.txt')
VIDEO_ID = re.compile(r'^[A-Za-z0-9_-]{11}$')
TOOLS_API = 'https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest'
NODE_SUMS = 'https://nodejs.org/download/release/latest-v22.x/SHASUMS256.txt'


def youtube_url(value):
    """Only a single public YouTube video, never arbitrary extractor URLs."""
    try:
        url = urllib.parse.urlsplit(value.strip())
        if (url.scheme not in ('http', 'https') or url.username or url.password or
                url.port is not None):
            raise ValueError()
        host = (url.hostname or '').lower()
        if host in ('youtu.be', 'www.youtu.be'):
            video = url.path.strip('/')
        elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'):
            if url.path == '/watch':
                videos = urllib.parse.parse_qs(url.query).get('v', [])
                video = videos[0] if len(videos) == 1 else ''
            else:
                match = re.fullmatch(r'/(?:shorts|live|embed)/([A-Za-z0-9_-]{11})/?', url.path)
                video = match.group(1) if match else ''
        else:
            raise ValueError()
        if not VIDEO_ID.fullmatch(video):
            raise ValueError()
        return 'https://www.youtube.com/watch?v=' + video, video
    except ValueError:
        raise Failure('Paste a link to one YouTube video, not a playlist or channel.') from None


def link_file(path):
    if path.stat().st_size > 64 * 1024:
        raise Failure('The link file is too large. Paste one YouTube link in the app instead.')
    try:
        if path.suffix.lower() == '.webloc':
            with path.open('rb') as stream:
                value = plistlib.load(stream).get('URL', '')
        else:
            value = path.read_text(encoding='utf-8-sig').strip()
            if path.suffix.lower() == '.url':
                values = re.findall(r'^URL=(.+)$', value, re.MULTILINE | re.IGNORECASE)
                value = values[0].strip() if len(values) == 1 else ''
        if not isinstance(value, str):
            raise ValueError()
        return youtube_url(value)[0]
    except (ValueError, TypeError, AttributeError, UnicodeError, plistlib.InvalidFileException):
        raise Failure('Could not read the link. Paste one YouTube link in the app instead.') from None


def tool_environment():
    env = os.environ.copy()
    # Do not inherit extra code injection paths/options into downloaded helpers.
    for name in ('NODE_OPTIONS', 'NODE_PATH', 'PYTHONPATH', 'PYTHONHOME'):
        env.pop(name, None)
    return env


def download_tool(url, destination, digest=None, limit=150 * 1024 ** 2):
    """Public HTTPS only; stream to disk, retry transient network failures."""
    if not url.startswith(('https://github.com/yt-dlp/yt-dlp/releases/download/',
                           'https://nodejs.org/download/release/',
                           'https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest')):
        raise Failure('Unexpected helper download address.')
    job_progress('Downloading YouTube helpers — this may take a few minutes')
    result = process_command(['/usr/bin/curl', '-q', '--fail', '--silent', '--show-error',
                             '--location', '--max-redirs', '5', '--proto', '=https',
                             '--proto-redir', '=https', '--connect-timeout', '15',
                             '--max-time', '900', '--retry', '2', '--max-filesize', str(limit),
                             '--output', str(destination), url], capture_output=True, text=True)
    if result.returncode:
        raise NetworkFailure('Could not download the YouTube helpers. Check your connection '
                             'and choose “Set up / update YouTube…” to retry.')
    if not destination.is_file() or not 0 < destination.stat().st_size <= limit:
        raise Failure('The helper download was empty or too large.')
    if digest and fingerprint(destination) != digest:
        raise Failure('A helper download failed its safety check. Nothing was installed; retry.')
    job_progress('Checking the downloaded helper')


def node_download(sums, machine):
    arch = {'x86_64': 'x64', 'arm64': 'arm64'}.get(machine)
    if arch is None:
        raise Failure('YouTube import needs an Intel or Apple Silicon Mac running macOS 11 or later.')
    pattern = r'^([0-9a-f]{64})\s+(node-v22\.\d+\.\d+-darwin-' + arch + r'\.tar\.gz)$'
    matches = re.findall(pattern, sums, re.MULTILINE)
    if len(matches) != 1:
        raise Failure('Could not find a verified Node 22 download for this Mac.')
    digest, filename = matches[0]
    version = filename.split('-')[1]
    return 'https://nodejs.org/download/release/' + version + '/' + filename, digest, filename


def unpack_node(archive, filename, destination):
    # Never extract the archive's directory tree, symlinks, or arbitrary paths.
    root = filename[:-len('.tar.gz')]
    try:
        with tarfile.open(archive, 'r:gz') as bundle:
            for member_name, target in ((root + '/bin/node', destination / 'node'),
                                        (root + '/LICENSE', destination / 'Node LICENSE.txt')):
                member = bundle.getmember(member_name)
                if not member.isfile() or not 0 < member.size <= 150 * 1024 ** 2:
                    raise Failure('The Node archive has an unexpected file.')
                with bundle.extractfile(member) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output)
        (destination / 'node').chmod(0o700)
    except (KeyError, tarfile.TarError):
        raise Failure('The Node archive could not be read. Retry the helper setup.') from None


def active_youtube_tools():
    home = HOME / 'YouTube Tools'
    try:
        name = json.loads((home / 'active.json').read_text())['bundle']
        if not re.fullmatch(r'bundle-[0-9a-f]{16}', name):
            return None
        bundle = home / name
        if all((bundle / name).is_file() and os.access(bundle / name, os.X_OK)
               for name in ('yt-dlp', 'node')):
            return bundle / 'yt-dlp', bundle / 'node'
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def mac_dialog(message, buttons=('Cancel', 'Enable')):
    def literal(value):
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    script = ('display dialog %s with title "Escape Pod Cast" buttons {%s} '
              'default button %s cancel button "Cancel"\nreturn button returned of result') % (
                  literal(message), ', '.join(literal(b) for b in buttons), literal(buttons[-1]))
    result = subprocess.run(['/usr/bin/osascript', '-'], input=script,
                            capture_output=True, text=True)
    if result.returncode:
        raise Failure('YouTube setup cancelled. Your existing audio publishing is unchanged.')
    return result.stdout.strip()


def install_youtube_tools():
    if sys.platform != 'darwin' or int(platform.mac_ver()[0].split('.')[0] or '0') < 11:
        raise Failure('YouTube import supports macOS 11 or later, including 11.7.11 and 15.7.')
    mac_dialog('Enable or update YouTube import?\n\n'
               'This downloads two free helpers (yt-dlp and Node 22) from their official sources. '
               'The downloads total about 90 MB; allow 400 MB of free disk space '
               'and a few minutes on a slow connection. '
               'No account, payment, administrator password, or Terminal commands are needed.\n\n'
               'Only import material you have permission to copy and publicly host. '
               'The podcast audio is public on GitHub.', buttons=('Cancel', 'Enable'))
    home = HOME / 'YouTube Tools'
    home.mkdir(parents=True, exist_ok=True)
    previous_tools = active_youtube_tools()
    print('Downloading and checking YouTube helpers…', flush=True)
    with tempfile.TemporaryDirectory(prefix='staging-', dir=home) as temp:
        staging = Path(temp)
        metadata, sums, archive = staging / 'release.json', staging / 'sums.txt', staging / 'node.tar.gz'
        download_tool(TOOLS_API, metadata, limit=2 * 1024 ** 2)
        try:
            release = json.loads(metadata.read_text())
            asset = next(a for a in release['assets'] if a['name'] == 'yt-dlp_macos')
            digest = asset['digest']
            tag = release['tag_name']
            if (not re.fullmatch(r'sha256:[0-9a-f]{64}', digest) or
                    not isinstance(tag, str) or not isinstance(asset['browser_download_url'], str)):
                raise ValueError()
        except (KeyError, ValueError, TypeError, StopIteration):
            raise Failure('Could not verify the official yt-dlp release. Retry later.') from None
        yt_digest = digest[7:]
        download_tool(NODE_SUMS, sums, limit=128 * 1024)
        url, digest, filename = node_download(sums.read_text(), platform.machine())
        try:
            installed_settings = json.loads((home / 'active.json').read_text())
        except (OSError, ValueError):
            installed_settings = {}
        if (previous_tools and installed_settings.get('yt_dlp') == tag and
                installed_settings.get('node') == filename):
            print('Your YouTube helpers are already up to date.', flush=True)
            return previous_tools
        download_tool(asset['browser_download_url'], staging / 'yt-dlp', yt_digest)
        (staging / 'yt-dlp').chmod(0o700)
        download_tool(url, archive, digest)
        unpack_node(archive, filename, staging)
        for executable in ('node', 'yt-dlp'):
            job_progress('Checking helper compatibility with this Mac')
            try:
                result = subprocess.run([str(staging / executable), '--version'],
                                        capture_output=True, text=True, timeout=60,
                                        env=tool_environment())
            except (OSError, subprocess.TimeoutExpired):
                raise Failure('The new YouTube helpers could not run on this Mac. '
                              'Your previous helpers are unchanged.') from None
            if result.returncode or (executable == 'node' and not result.stdout.startswith('v22.')):
                raise Failure('The new YouTube helpers are not compatible with this Mac. '
                              'Your previous helpers are unchanged.')
        # Only switch after both tools are verified and have run successfully.
        # Move the checked files, avoiding a second large copy on older Macs.
        name = 'bundle-' + secrets.token_hex(8)
        installed = home / name
        installed.mkdir()
        for file in ('yt-dlp', 'node', 'Node LICENSE.txt'):
            shutil.move(str(staging / file), str(installed / file))
        pointer = staging / 'active.json'
        pointer.write_text(json.dumps({'bundle': name, 'yt_dlp': tag,
                                       'node': filename}))
        os.replace(pointer, home / 'active.json')
    # Keep the current and one previous working bundle; remove only our complete,
    # known helper folders. Extra user files cause a folder to be left alone.
    keep = {name}
    if previous_tools:
        keep.add(previous_tools[0].parent.name)
    for bundle in home.iterdir():
        if (bundle.name not in keep and re.fullmatch(r'bundle-[0-9a-f]{16}', bundle.name) and
                bundle.is_dir() and not bundle.is_symlink()):
            try:
                if {path.name for path in bundle.iterdir()} == {'yt-dlp', 'node', 'Node LICENSE.txt'}:
                    shutil.rmtree(bundle)
            except OSError:
                pass  # A cleanup problem must not report a verified update as failed.
    print('YouTube helpers are ready.', flush=True)
    return active_youtube_tools()


def download_youtube(url, video, directory, tools):
    job_progress('Downloading YouTube audio', percent=0)
    downloader, node = tools
    output = directory / 'download.log'
    args = [str(downloader), '--ignore-config', '--no-plugin-dirs', '--no-js-runtimes',
            '--js-runtimes', 'node:' + str(node), '--no-remote-components',
            '--no-playlist', '--newline', '--progress', '--progress-delta', '0.5',
            '--progress-template', 'download:EPC_PROGRESS %(progress._percent_str)s',
            '--no-colors', '--socket-timeout', '20',
            '--retries', '3', '--fragment-retries', '3', '--abort-on-unavailable-fragments',
            '--max-filesize', str(2 * 1024 ** 3 - 1), '--match-filters', '!is_live',
            '--format', 'bestaudio[ext=m4a]', '--fixup', 'never', '--write-info-json',
            '--output', str(directory / 'audio.%(ext)s'), '--', url]
    print('Getting YouTube audio: ' + url, flush=True)
    try:
        with output.open('w') as log:
            result = process_command(args, stdout=log, stderr=subprocess.STDOUT,
                                     timeout=7200, env=tool_environment(),
                                     progress_file=output, progress_kind='youtube')
    except subprocess.TimeoutExpired:
        raise Failure('The YouTube download timed out. Check your connection and retry.') from None
    if result.returncode:
        with output.open('rb') as log:
            log.seek(max(0, output.stat().st_size - 4000))
            detail = log.read().decode('utf-8', errors='replace')
        print(detail, file=sys.stderr, flush=True)
        raise Failure('YouTube audio could not be downloaded. The video may be unavailable, '
                      'restricted, blocked by YouTube, or have no compatible audio. '
                      'For an ordinary public video, try “Set up / update YouTube…” and retry. '
                      'No sign-in, browser cookies, or access restrictions are bypassed.')
    media, info = directory / 'audio.m4a', directory / 'audio.info.json'
    try:
        if info.stat().st_size > 16 * 1024 ** 2:
            raise ValueError()
        metadata = json.loads(info.read_text())
        if (metadata.get('id') != video or metadata.get('is_live') or
                metadata.get('live_status') in ('is_live', 'is_upcoming') or
                not media.is_file() or not 0 < media.stat().st_size < 2 * 1024 ** 3):
            raise ValueError()
        title = metadata.get('title')
        if not isinstance(title, str) or not title.strip():
            raise ValueError()
        # Remove characters XML 1.0 cannot represent; filenames never use this title.
        title = ''.join(c for c in title if c in '\t\n\r' or
                        0x20 <= ord(c) <= 0xd7ff or 0xe000 <= ord(c) <= 0xfffd or
                        0x10000 <= ord(c) <= 0x10ffff).strip()[:1000]
        if not title:
            raise ValueError()
    except (OSError, ValueError, TypeError, AttributeError):
        raise Failure('YouTube did not return complete audio for that video. '
                      'Live or upcoming streams are not supported; retry a finished video.') from None
    return media, title


def publish_youtube(client, release, value, now, prompt=True):
    url, video = youtube_url(value)
    identity = hashlib.sha256(('youtube:' + video).encode('ascii')).hexdigest()
    existing = next((a for a in client.assets(release)
                     if a['name'] == 'epc-' + identity + '.m4a' and
                     a.get('state') == 'uploaded' and stamp(a['created_at']) > now - RETENTION), None)
    if existing:
        # A failed feed update can be retried without redownloading/reuploading audio.
        job_progress('Reusing your completed audio upload', label=existing.get('label') or 'YouTube · ' + video)
        verify_enclosure(existing['browser_download_url'], existing['size'])
        publication_boundary()
        root, sha = client.read_feed()
        if add_episode(root, existing, (CURRENT_JOB or {}).get('title') or existing.get('label') or 'YouTube ' + video,
                       now, (CURRENT_JOB or {}).get('description')):
            client.write_feed(root, sha)
        remember_episode(existing, now)
        print('Published existing YouTube audio: ' + video, flush=True)
        return
    tools = active_youtube_tools()
    if tools is None:
        if not prompt:
            raise Failure('Open the app and choose “Set up / update YouTube…” first.')
        tools = install_youtube_tools()
    with tempfile.TemporaryDirectory() as temp:
        media, title = download_youtube(url, video, Path(temp), tools)
        publish(client, release, media, now, title=title, identity=identity)


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
        mark_asset_removed(asset['id'], 'expired')
    print('Removed %s expired audio file(s).' % len(expired), flush=True)


def get_token(repo):
    result = subprocess.run(['/usr/bin/security', 'find-generic-password',
                             '-s', SERVICE, '-a', repo, '-w'],
                            capture_output=True, text=True)
    if result.returncode:
        raise Failure('GitHub credential unavailable. Run Install.command again.')
    return result.stdout.strip()


def setup(repo, token=None, progress=None):
    with locked():
        return setup_locked(repo, token, progress)


def setup_locked(repo, token=None, progress=None):
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
    report('Preparing your random podcast address…')
    feed_path = client.initialize_feed()
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
    feed_url = pages['html_url'].rstrip('/') + '/' + feed_path[len('docs/'):]
    config = {'repo': repo, 'feed_url': feed_url, 'feed_path': feed_path}
    CONFIG.write_text(json.dumps(config, indent=2))
    (HOME / 'Feed URL.txt').write_text(feed_url + '\n')
    print('\nFollow this once in Apple Podcasts:\n' + feed_url +
          '\nPages may take a few minutes to publish. Enable automatic downloads.')
    return config


@contextlib.contextmanager
def locked(blocking=True):
    HOME.mkdir(parents=True, exist_ok=True)
    with (HOME / 'publisher.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        yield True


def process_files(client, release, paths, now, prompt=True, track=False):
    failed = []
    for path in paths:
        try:
            with record_folder_file(path) if track else contextlib.nullcontext():
                if path.suffix.lower() in LINK_TYPES:
                    publish_youtube(client, release, link_file(path), now, prompt=prompt)
                else:
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
    parser.add_argument('--youtube', metavar='VIDEO_URL')
    parser.add_argument('--youtube-setup', action='store_true')
    parser.add_argument('--job', metavar='TASK_ID')
    parser.add_argument('files', nargs='*', type=Path)
    args = parser.parse_args()
    if args.job:
        run_job(args.job)
        return
    if args.setup:
        setup(args.setup)
        return
    if not args.maintain and (args.files or args.youtube):
        jobs, errors = [], []
        for kind, source in [('file', path) for path in args.files] + ([('youtube', args.youtube)] if args.youtube else []):
            try:
                jobs.append(create_job(kind, source))
            except (Failure, OSError, ValueError) as exc:
                errors.append(str(exc))
        for job in jobs:
            run_job(job['id'])
        if errors or any(load_job(job['id'])['state'] == 'failed' for job in jobs):
            raise Failure('Some items need attention. Successful items are kept; open the app to retry. ' + '\n'.join(errors))
        return
    if args.maintain:
        recover_jobs()
        inbox = HOME / 'Drop Audio Here'
        inbox.mkdir(parents=True, exist_ok=True)
        if not queue_paused():
            history = list_jobs()
            for path in inbox.iterdir():
                if (path.is_file() and not path.name.startswith('.') and path.suffix.lower() in AUDIO_TYPES + LINK_TYPES
                        and dt.datetime.now().timestamp() - path.stat().st_mtime >= 60):
                    previous = next((job for job in reversed(history) if job.get('origin') == 'folder' and
                                     job['source'] == str(path.resolve()) and job['state'] in ('failed', 'queued', 'running')), None)
                    if previous is not None:
                        continue
                    try:
                        job = create_job('file', path, allow_invalid_link=True)
                        with job_lock(job['id'], blocking=False) as acquired:
                            if acquired:
                                job = load_job(job['id'])
                                if job['state'] in ('queued', 'failed'):
                                    job['origin'] = 'folder'
                                    save_job(job)
                    except (Failure, OSError, ValueError) as exc:
                        print('Drop folder: ' + str(exc), file=sys.stderr, flush=True)
        # Queued items survive closing the window or restarting the Mac.
        for job in list_jobs():
            if ready_job(job):
                run_job(job['id'], blocking=False)
        confirm_publications()
    with locked(blocking=not args.maintain) as acquired:
        if not acquired:
            return
        if args.youtube_setup:
            install_youtube_tools()
            return
        if not CONFIG.exists():
            raise Failure('Run Install.command first.')
        config = json.loads(CONFIG.read_text())
        inbox = HOME / 'Drop Audio Here'
        candidates = []
        if args.maintain:
            inbox.mkdir(exist_ok=True)
            last = HOME / 'last-cleanup'
            if not candidates and last.exists() and not args.files and not args.youtube:
                if dt.datetime.now().timestamp() - last.stat().st_mtime < 3600:
                    return
        client = GitHub(config['repo'], get_token(config['repo']))
        release = client.request('GET', '/releases/tags/audio')
        now = dt.datetime.now(dt.timezone.utc)
        failed = process_files(client, release, args.files, now)
        if args.youtube:
            try:
                publish_youtube(client, release, args.youtube, now)
            except (Failure, OSError, ValueError, ET.ParseError) as exc:
                print('Failed: YouTube link: ' + str(exc), file=sys.stderr, flush=True)
                failed.append(args.youtube)
        cleanup(client, release, now)
        (HOME / 'last-cleanup').touch()
        if failed:
            raise Failure('%s item(s) failed. Successful items are already published. '
                          'Retry failures; see Status.log for details.' % len(failed))


if __name__ == '__main__':
    try:
        main()
        if '--notify' in sys.argv:
            message = ('YouTube helpers are ready. Open the app and choose “Paste YouTube link…”.'
                       if '--youtube-setup' in sys.argv else
                       'Audio accepted. Open the app for publication and retry status; Apple controls later downloads.')
            subprocess.run(['/usr/bin/osascript', '-e',
                            'display dialog "' + message + '" buttons {"OK"} '
                            'default button "OK" with title "Escape Pod Cast"'])
    except (Failure, OSError, ValueError, ET.ParseError) as exc:
        print(str(exc), file=sys.stderr)
        if '--notify' in sys.argv:
            answer = subprocess.run(['/usr/bin/osascript', '-e',
                            'display dialog "Publishing needs attention. Open Status.log '
                            'using the app’s Open publishing log action for details, then retry." '
                            'buttons {"OK", "Open Log"} default button "Open Log" '
                            'with title "Escape Pod Cast"'], capture_output=True, text=True)
            if 'Open Log' in answer.stdout:
                subprocess.run(['/usr/bin/open', str(HOME / 'Status.log')])
        sys.exit(1)
