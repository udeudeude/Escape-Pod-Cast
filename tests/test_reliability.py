"""Real queue/file transactions and publication lifecycle regression checks."""
import datetime as dt
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import threading
import time
import os
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).parents[1] / 'mac'))
import escape_pod_cast as p
import app
import install


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        for item in (patch.object(p, 'HOME', self.home), patch.object(p, 'CONFIG', self.home/'config.json')):
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(lambda: setattr(p, 'CURRENT_JOB', None))
        self.audio = self.home/'🎧 Source + track.mp3'
        self.audio.write_bytes(b'original audio')

    def test_transfer_percent_is_phase_scoped_and_parses_both_tools(self):
        job = p.create_job('file', self.audio)
        p.CURRENT_JOB = job
        p.job_progress('Downloading YouTube audio', percent=0)
        p.parse_transfer_progress('EPC_PROGRESS  42.3%\n', 'youtube')
        self.assertEqual(p.load_job(job['id'])['percent'], 42.3)
        p.job_progress('Converting audio')
        self.assertIsNone(p.load_job(job['id'])['percent'])
        p.job_progress('Uploading audio', percent=0)
        p.parse_transfer_progress(' 50 100M 0 0 50 50M 0 1024k 0:01:40 0:00:50 0:00:50 1024k\r', 'curl')
        self.assertEqual(p.load_job(job['id'])['percent'], 50)
        p.publication_boundary()
        with self.assertRaisesRegex(p.Failure, 'finishing'):
            job['state'] = 'running'
            p.save_job(job)
            p.request_abort(job['id'])

    def test_abort_real_child_cleans_temporary_download_and_can_delete_record(self):
        for delete in (False, True):
            with self.subTest(delete=delete):
                job = p.create_job('file', self.audio)
                ready = threading.Event()
                temporary = []
                errors = []
                def perform(current):
                    with tempfile.TemporaryDirectory(dir=self.home) as folder:
                        directory = Path(folder)
                        temporary.append(directory)
                        pid_file = directory/'pid'
                        ready.set()
                        code = 'import os,sys,time;from pathlib import Path;Path(sys.argv[1]).write_text(str(os.getpid()));time.sleep(30)'
                        p.process_command([sys.executable, '-c', code, str(pid_file)], capture_output=True,
                                          text=True, timeout=5)
                def abort():
                    try:
                        self.assertTrue(ready.wait(5))
                        deadline = time.monotonic()+5
                        while not (temporary[0]/'pid').exists() and time.monotonic() < deadline:
                            time.sleep(.01)
                        pid = int((temporary[0]/'pid').read_text())
                        p.request_abort(job['id'], delete=delete)
                        temporary.append(pid)
                    except Exception as exc:
                        errors.append(exc)
                thread = threading.Thread(target=abort)
                thread.start()
                with patch.object(p, 'perform_job', side_effect=perform):
                    p.run_job(job['id'])
                thread.join(6)
                self.assertFalse(thread.is_alive())
                self.assertEqual(errors, [])
                self.assertFalse(temporary[0].exists())
                with self.assertRaises(ProcessLookupError):
                    os.kill(temporary[1], 0)
                self.assertEqual(self.audio.read_bytes(), b'original audio')
                if delete:
                    self.assertFalse(p.job_path(job['id']).exists())
                else:
                    self.assertEqual(p.load_job(job['id'])['state'], 'cancelled')
                    p.retry_job(job['id'])
                    self.assertEqual(p.load_job(job['id'])['state'], 'queued')
                    p.cancel_job(job['id'], delete=True)

    def test_monitored_process_handles_stdin_and_timeout(self):
        p.CURRENT_JOB = p.create_job('file', self.audio)
        result = p.process_command([sys.executable, '-c', 'import sys,time;v=sys.stdin.read();time.sleep(.3);print(v)'],
                                   input='configured input', capture_output=True, text=True, timeout=3)
        self.assertEqual(result.stdout.strip(), 'configured input')
        with self.assertRaises(subprocess.TimeoutExpired):
            p.process_command([sys.executable, '-c', 'import time;time.sleep(30)'],
                              capture_output=True, text=True, timeout=.1)

    def test_delete_watched_import_preserves_source_and_prevents_rescan(self):
        inbox = self.home/'Drop Audio Here'
        inbox.mkdir()
        source = inbox/'track.mp3'
        source.write_bytes(b'original')
        job = p.create_job('file', source)
        job['origin'] = 'folder'
        p.save_job(job)
        p.cancel_job(job['id'], delete=True)
        self.assertFalse(p.job_path(job['id']).exists())
        self.assertFalse(source.exists())
        self.assertEqual((inbox/'Not Published/track.mp3').read_bytes(), b'original')

    def test_concurrent_intake_and_link_forms_share_one_waiting_job(self):
        job = p.create_job('file', self.audio)
        code = 'import sys;sys.path.insert(0,sys.argv[1]);import escape_pod_cast as p;from pathlib import Path;p.HOME=Path(sys.argv[2]);print(p.create_job("file",sys.argv[3])["id"])'
        result = subprocess.run([sys.executable, '-c', code, str(Path(p.__file__).parent),
                                 str(self.home), str(self.audio)], capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), job['id'])
        link = self.home/'video.webloc'
        link.write_bytes(plistlib.dumps({'URL': 'https://youtu.be/BaW_jenozKc'}))
        first = p.create_job('file', link)
        second = p.create_job('youtube', 'https://www.youtube.com/watch?v=BaW_jenozKc&si=x')
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(len(p.list_jobs()), 2)

    def test_bounded_retry_schedule_survives_pause_and_does_not_spin(self):
        job = p.create_job('file', self.audio)
        with patch.object(p, 'perform_job', side_effect=p.NetworkFailure('connection timed out')) as perform:
            p.run_job(job['id'])
            first = p.load_job(job['id'])
            self.assertEqual((first['state'], first['auto_retries']), ('queued', 1))
            self.assertFalse(p.ready_job(first))
            p.run_job(job['id'])
            self.assertEqual(perform.call_count, 1)
            p.pause_queue(True)
            first['next_attempt'] = '2000-01-01T00:00:00+00:00'
            p.save_job(first)
            self.assertFalse(p.ready_job(first))
            p.pause_queue(False)
            for _ in range(3):
                current = p.load_job(job['id'])
                current['next_attempt'] = '2000-01-01T00:00:00+00:00'
                p.save_job(current)
                p.run_job(job['id'])
            self.assertEqual(perform.call_count, 4)
        self.assertEqual(p.load_job(job['id'])['state'], 'failed')
        self.assertEqual(self.audio.read_bytes(), b'original audio')
        p.retry_job(job['id'])
        self.assertEqual(p.load_job(job['id'])['auto_retries'], 0)

    def test_bad_credentials_and_certificate_failures_are_not_auto_retried(self):
        for error in (p.Failure('GitHub returned 403'), p.NetworkFailure('macOS could not verify the server certificate.')):
            job = {'attempts': 1}
            p.fail_job(job, error)
            self.assertEqual(job['state'], 'failed')
        client = p.GitHub('owner/repo', 'secret')
        with patch.object(sys, 'platform', 'darwin'), patch.object(p, 'mac_transfer', return_value=(503, b'', {})):
            with self.assertRaises(p.NetworkFailure):
                client.request('GET', '')

    def episode(self):
        job = p.create_job('file', self.audio)
        now = dt.datetime.now(dt.timezone.utc)
        job.update(state='done', publication='feed_pending', asset_id=7, guid='escape-pod-cast:asset-7',
                   enclosure='https://example.com/audio.m4a', expires_at=(now+p.RETENTION).isoformat())
        p.save_job(job)
        p.CONFIG.write_text(json.dumps({'repo': 'owner/repo', 'feed_url': 'https://example.com/feed.xml'}))
        return job

    def test_feed_confirmation_requires_matching_guid_and_enclosure(self):
        job = self.episode()
        root = p.new_feed()
        asset = {'id': 7, 'browser_download_url': 'https://example.com/wrong.m4a', 'size': 42, 'content_type': 'audio/mp4'}
        p.add_episode(root, asset, 'A title', dt.datetime.now(dt.timezone.utc))
        with patch.object(sys, 'platform', 'darwin'), patch.object(p, 'mac_transfer') as transfer:
            transfer.return_value = (200, ET.tostring(root), {})
            p.confirm_publications()
            self.assertEqual(p.load_job(job['id'])['publication'], 'feed_pending')
            root.find('channel/item/enclosure').set('url', job['enclosure'])
            transfer.return_value = (200, ET.tostring(root), {})
            p.confirm_publications()
        self.assertEqual(p.load_job(job['id'])['publication'], 'available')
        self.assertIn('Apple controls', p.load_job(job['id'])['message'])

    def test_expiry_due_is_not_claimed_as_deleted_before_cleanup(self):
        job = self.episode()
        job['publication'] = 'available'
        job['expires_at'] = '2000-01-01T00:00:00+00:00'
        p.save_job(job)
        self.assertEqual(p.episode_status(job), 'Expiry due')
        p.mark_asset_removed(7, 'expired')
        self.assertEqual(p.episode_status(p.load_job(job['id'])), 'Expired')
        self.assertEqual(app.transmission_position(p.load_job(job['id']))[:2], (0, 'EXPIRED'))

    def test_reordering_and_edits_preserve_originals(self):
        first = p.create_job('file', self.audio)
        second = p.create_job('check')
        p.pause_queue(True)
        p.move_job(second['id'], -1)
        self.assertEqual([job['id'] for job in p.list_jobs()], [second['id'], first['id']])
        p.edit_job(first['id'], 'Custom title', 'A description & <markup>')
        edited = p.load_job(first['id'])
        self.assertEqual(edited['title'], 'Custom title')
        root = p.new_feed()
        asset = {'id': 2, 'browser_download_url': 'https://example.com/audio', 'size': 2, 'content_type': 'audio/mpeg'}
        p.add_episode(root, asset, edited['title'], dt.datetime.now(dt.timezone.utc), edited['description'])
        rebuilt = ET.fromstring(ET.tostring(root))
        self.assertEqual(rebuilt.findtext('channel/item/description'), edited['description'])
        self.assertEqual(self.audio.read_bytes(), b'original audio')

    def test_deletion_never_deletes_audio_before_successful_feed_write(self):
        job = self.episode()
        root = p.new_feed()
        asset = {'id': 7, 'browser_download_url': job['enclosure'], 'size': 2, 'content_type': 'audio/mp4'}
        p.add_episode(root, asset, 'Audio', dt.datetime.now(dt.timezone.utc))
        client = Mock()
        client.read_feed.return_value = (root, 'sha')
        client.write_feed.side_effect = p.Failure('conflicting write')
        with patch.object(p, 'GitHub', return_value=client), patch.object(p, 'get_token', return_value='secret'):
            with self.assertRaises(p.Failure):
                p.delete_episode(job['id'])
            client.request.assert_not_called()
            client.write_feed.side_effect = None
            p.delete_episode(job['id'])
        client.request.assert_called_once_with('DELETE', '/releases/assets/7', missing=True)
        self.assertEqual(p.load_job(job['id'])['publication'], 'removed')
        self.assertTrue(self.audio.exists())

    def test_diagnostics_redact_tokens_address_and_home_paths(self):
        secret = 'github_pat_' + 'a'*40
        feed = 'https://owner.github.io/repo/feeds/' + 'b'*48 + '/feed.xml'
        (self.home/'Status.log').write_text(secret + '\nAuthorization: Bearer random-secret\n' + feed + '\n' + str(self.home))
        report = json.dumps(p.diagnostic_report())
        for value in (secret, 'random-secret', 'b'*48, str(self.home)):
            self.assertNotIn(value, report)

    def test_audio_timeout_and_converter_detail_remain_actionable(self):
        with patch.object(p.subprocess, 'run', side_effect=subprocess.TimeoutExpired('afinfo', 30)):
            with self.assertRaisesRegex(p.Failure, 'timed out'):
                p.audio_command(['afinfo'], timeout=30)
        wav = self.home/'bad.wav'
        wav.write_bytes(b'bad audio')
        with patch.object(p.shutil, 'which', return_value='ffmpeg'), patch.object(p, 'audio_command') as command:
            command.return_value = subprocess.CompletedProcess([], 1, '', 'Invalid data found when processing input')
            with self.assertRaisesRegex(p.Failure, 'Invalid data'):
                p.prepare_audio(wav, self.home)

    def test_native_click_stays_outside_tk(self):
        import queue
        from types import SimpleNamespace
        bridge = app.MacDropZone.__new__(app.MacDropZone)
        bridge.window = SimpleNamespace(drop_messages=queue.Queue())
        bridge.event('click', None)
        self.assertEqual(bridge.window.drop_messages.get_nowait(), ('choose', None))

    def test_symlinked_support_folder_still_archives_and_cancels_original(self):
        support = self.home/'real-support'
        support.mkdir()
        alias = self.home/'alias-support'
        alias.symlink_to(support, target_is_directory=True)
        inbox = alias/'Drop Audio Here'
        inbox.mkdir()
        source = inbox/'track.mp3'
        source.write_bytes(b'original')
        with patch.object(p, 'HOME', alias), patch.object(p, 'CONFIG', alias/'config.json'):
            p.CONFIG.write_text(json.dumps({'repo': 'owner/repo'}))
            job = p.create_job('file', source)
            job['origin'] = 'folder'
            p.save_job(job)
            with patch.object(p, 'publish'), patch.object(p, 'GitHub'), patch.object(p, 'get_token', return_value='test'):
                p.run_job(job['id'])
            self.assertTrue((inbox/'Published/track.mp3').exists())
            self.assertFalse(source.exists())
            source.write_bytes(b'second original')
            waiting = p.create_job('file', source)
            waiting['origin'] = 'folder'
            p.save_job(waiting)
            p.cancel_job(waiting['id'])
            self.assertTrue((inbox/'Not Published/track.mp3').exists())


class InstallerTransactionTests(unittest.TestCase):
    def test_failed_runtime_replace_restores_app_scripts_and_agent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home, target, agent = root/'support', root/'App.app', root/'agent.plist'
            home.mkdir()
            target.mkdir()
            (target/'old').write_text('old app')
            agent.write_bytes(plistlib.dumps({'Label': 'old'}))
            for filename in install.RUNTIME_FILES:
                (home/filename).write_text('old ' + filename)
            def run(args, **kwargs):
                if args[0] == '/usr/bin/osacompile':
                    Path(args[2]).mkdir()
                return subprocess.CompletedProcess(args, 0)
            original = install.shutil.copy2
            def copy(source, destination, *args, **kwargs):
                if Path(destination).name == 'app.py.new':
                    raise OSError('simulated copy failure')
                return original(source, destination, *args, **kwargs)
            with patch.object(install, 'HOME', home), patch.object(install, 'APP', target), patch.object(install, 'AGENT', agent), \
                    patch.object(p, 'HOME', home), patch.object(install.subprocess, 'run', side_effect=run), \
                    patch.object(install.shutil, 'copy2', side_effect=copy):
                with self.assertRaisesRegex(OSError, 'simulated'):
                    install.install_app({'feed_url': 'https://example.com/feed'})
            for filename in install.RUNTIME_FILES:
                self.assertEqual((home/filename).read_text(), 'old ' + filename)
            self.assertEqual((target/'old').read_text(), 'old app')
            self.assertEqual(plistlib.loads(agent.read_bytes()), {'Label': 'old'})
            self.assertFalse((home/'Installing Backup').exists())

    def test_rollback_swaps_complete_versions_and_preserves_user_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home, target, agent = root/'support', root/'App.app', root/'agent.plist'
            home.mkdir(); target.mkdir()
            config = home/'config.json'
            config.write_text('user connection')
            for filename in install.RUNTIME_FILES:
                (home/filename).write_text('previous ' + filename)
            (target/'version').write_text('previous')
            with patch.object(install, 'HOME', home), patch.object(install, 'APP', target), patch.object(install, 'AGENT', agent), \
                    patch.object(p, 'HOME', home), patch.object(install, 'load_agent'):
                install.snapshot_version(home/'Previous Version')
                for filename in install.RUNTIME_FILES:
                    (home/filename).write_text('current ' + filename)
                (target/'version').write_text('current')
                install.rollback_app()
                self.assertEqual((target/'version').read_text(), 'previous')
                self.assertEqual((home/'Previous Version/App.app/version').read_text(), 'current')
                self.assertEqual(config.read_text(), 'user connection')

    def test_downloadable_app_has_portable_launcher_and_executable_zip_mode(self):
        import importlib.util
        source = Path(__file__).parents[1]/'tools/build_mac_app.py'
        spec = importlib.util.spec_from_file_location('builder', source)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as temp:
            archive = builder.build(temp)
            with zipfile.ZipFile(archive) as bundle:
                prefix = 'Escape Pod Cast Setup.app/Contents/'
                info = plistlib.loads(bundle.read(prefix+'Info.plist'))
                self.assertEqual(info['LSMinimumSystemVersion'], '11.0')
                launcher = bundle.getinfo(prefix+'MacOS/setup')
                self.assertTrue((launcher.external_attr >> 16) & 0o111)
                self.assertTrue(bundle.read(launcher).startswith(b'#!/bin/bash'))
                self.assertIn(prefix+'Resources/mac/app.py', bundle.namelist())


if __name__ == '__main__':
    unittest.main()
