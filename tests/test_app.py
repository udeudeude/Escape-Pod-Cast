"""Durable queue, recovery, UI actions, and the update/install boundaries."""
import datetime as dt
import json
import os
import queue
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
import zipfile

sys.path.insert(0, str(Path(__file__).parents[1] / 'mac'))
import escape_pod_cast as p
import app
import install


class AppFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve()
        for mock in (patch.object(p, 'HOME', self.home),
                     patch.object(p, 'CONFIG', self.home / 'config.json')):
            mock.start()
            self.addCleanup(mock.stop)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(lambda: setattr(p, 'CURRENT_JOB', None))
        self.audio = self.home / 'Rock & <Roll>.mp3'
        self.audio.write_bytes(b'original')


class DropTests(AppFixture):
    def test_multiple_files_uri_unicode_and_duplicates(self):
        second = self.home / '🎧 {Hound} + Heaven.m4a'
        second.write_bytes(b'audio')
        accepted, rejected = app.drop_inputs([self.audio.as_uri(), second.as_uri(), str(second)])
        self.assertEqual(accepted, [('file', str(self.audio)), ('file', str(second))])
        self.assertEqual(rejected, [])

    def test_video_links_normalize_and_mixed_bad_inputs_do_not_discard_audio(self):
        accepted, rejected = app.drop_inputs([str(self.audio), 'https://youtu.be/BaW_jenozKc?si=tracking',
                                            'https://example.com', str(self.home), 'file://remote/audio.mp3'])
        self.assertEqual(len(accepted), 2)
        self.assertEqual(accepted[1], ('youtube', 'https://www.youtube.com/watch?v=BaW_jenozKc'))
        self.assertEqual(len(rejected), 3)
        self.assertEqual(p.list_jobs(), [])  # Drag preview never writes jobs.

    def test_saved_link_and_unsupported_file(self):
        link = self.home / 'video.url'
        link.write_text('[InternetShortcut]\nURL=https://youtu.be/BaW_jenozKc\n')
        other = self.home / 'document.pdf'
        other.write_bytes(b'not audio')
        accepted, rejected = app.drop_inputs([str(link), str(other)])
        self.assertEqual(accepted, [('youtube', 'https://www.youtube.com/watch?v=BaW_jenozKc')])
        self.assertEqual(len(rejected), 1)

    def test_repeated_drop_reuses_waiting_job_and_reports_partial_failure(self):
        window = app.Window.__new__(app.Window)
        window.show_error = Mock()
        self.assertTrue(window.queue_drop([str(self.audio), 'https://example.com']))
        self.assertTrue(window.queue_drop([self.audio.as_uri()]))
        self.assertEqual(len(p.list_jobs()), 1)
        self.assertEqual(window.selected, p.list_jobs()[0]['id'])
        window.show_error.assert_called_once()

    def test_native_perform_defers_work_and_copy_preview_does_not_publish(self):
        bridge = app.MacDropZone.__new__(app.MacDropZone)
        # Deliberately expose no root, widget, draw or queue_drop methods.
        # Native callbacks must never enter Tcl, even to schedule an idle task.
        bridge.window = SimpleNamespace(updating=False, drop_messages=queue.Queue())
        bridge.values = Mock(return_value=[str(self.audio)])
        self.assertTrue(bridge.event('preview', None))
        self.assertEqual(bridge.window.drop_messages.get_nowait(), ('preview', ('Release to publish', True)))
        self.assertEqual(p.list_jobs(), [])
        self.assertTrue(bridge.event('perform', None))
        self.assertEqual(bridge.window.drop_messages.get_nowait(), ('drop', (str(self.audio),)))
        self.assertEqual(bridge.window.drop_messages.get_nowait(), ('preview', (None, False)))
        bridge.event('exit', None)
        self.assertEqual(bridge.window.drop_messages.get_nowait(), ('preview', (None, False)))
        self.assertEqual(p.list_jobs(), [])
        bridge.window.updating = True
        self.assertFalse(bridge.event('prepare', None))
        self.assertFalse(bridge.event('perform', None))
        self.assertEqual(bridge.window.drop_messages.get_nowait(), ('preview', (None, False)))
        self.assertTrue(bridge.window.drop_messages.empty())

    def test_tk_timer_consumes_native_messages_and_coalesces_highlights(self):
        window = app.Window.__new__(app.Window)
        window.drop_messages = queue.Queue()
        window.root, window.draw_drop, window.queue_drop = Mock(), Mock(), Mock()
        window.updating = False
        window.drop_messages.put(('preview', ('Release to publish', True)))
        window.drop_messages.put(('drop', (str(self.audio),)))
        window.drop_messages.put(('preview', (None, False)))
        window.process_drop_messages()
        window.draw_drop.assert_called_once_with(None, False)
        window.queue_drop.assert_called_once_with((str(self.audio),))
        window.root.after.assert_called_once_with(75, window.process_drop_messages)
        self.assertTrue(window.drop_messages.empty())

    def test_native_geometry_handles_flipped_and_unflipped_content(self):
        bridge = app.MacDropZone.__new__(app.MacDropZone)
        bridge.view, bridge.parent = 1, 2
        root, zone = Mock(), Mock()
        root.winfo_rootx.return_value, root.winfo_rooty.return_value = 100, 200
        zone.winfo_rootx.return_value, zone.winfo_rooty.return_value = 120, 280
        zone.winfo_width.return_value, zone.winfo_height.return_value = 600, 96
        bridge.window = Mock(root=root, drop_zone=zone)
        bridge.bounds = Mock(return_value=app._Rect(app._Point(0, 0), app._Size(860, 760)))
        for flipped, expected_y in ((False, 584), (True, 80)):
            bridge.send = Mock(return_value=flipped)
            bridge.resize()
            rect = bridge.send.call_args.args[2]
            self.assertEqual((rect.origin.x, rect.origin.y, rect.size.width, rect.size.height),
                             (20, expected_y, 600, 96))


class RadioDesignTests(unittest.TestCase):
    def test_dial_tracks_real_stages_not_percentages(self):
        job = {'kind': 'file', 'state': 'queued'}
        self.assertEqual(app.transmission_position(job)[:2], (0, 'WAITING'))
        job.update(state='running', stage='Converting source audio')
        self.assertEqual(app.transmission_position(job)[:2], (1, 'PREPARING'))
        for stage in ('Uploading', 'Checking playback', 'Updating feed'):
            job['stage'] = stage
            self.assertEqual(app.transmission_position(job)[:2], (2, 'TRANSMITTING'))
        job['state'] = 'done'
        job['publication'] = 'available'
        self.assertEqual(app.transmission_position(job)[:2], (3, 'ON AIR'))
        job['kind'] = 'check'
        self.assertEqual(app.transmission_position(job)[:2], (0, 'READY'))
        job['state'] = 'failed'
        self.assertEqual(app.transmission_position(job)[:2], (0, 'CHECK SIGNAL'))
        self.assertEqual(app.transmission_position(job, updating=True)[:2], (0, 'TUNING'))
        self.assertEqual(app.transmission_position()[:2], (0, 'READY'))

    def test_hatch_and_dial_stay_in_bounds_at_small_and_large_widths(self):
        window = app.Window.__new__(app.Window)
        window.drop_preview, window.hatch_pulse, window.lamp_tick = (None, False), 0, False
        window.jobs, window.selected, window.updating, window.drop_bridge = {}, None, False, None
        window.drop_hint = 'Drop here — publishing starts automatically'
        for width in (618, 828):
            canvas = Mock()
            canvas.winfo_width.return_value = width
            window.drop_zone = canvas
            window.draw_drop()
            labels = [call.kwargs['text'] for call in canvas.create_text.call_args_list]
            self.assertIn('FEED ME AUDIO', labels)
            self.assertIn('READY', labels)
            for method in (canvas.create_oval, canvas.create_line):
                for call in method.call_args_list:
                    coords = call.args
                    self.assertTrue(all(0 <= value <= width for value in coords[::2]))
                    self.assertTrue(all(0 <= value <= 154 for value in coords[1::2]))

    def test_tape_rack_reuses_real_buttons_and_supports_keyboard_navigation(self):
        canvas = Mock()
        canvas.winfo_width.return_value, canvas.winfo_height.return_value = 618, 180
        canvas.yview.return_value, canvas.canvasy.return_value = (0, 1), 0
        tk = Mock()
        tk.Canvas.return_value = canvas
        tk.Button.side_effect = lambda *args, **kwargs: Mock()
        deck = app.TapeDeck(Mock(), tk)
        deck.bind('<<TreeviewSelect>>', Mock())
        for n, key in enumerate(('one', 'two', 'three')):
            deck.insert('', 'end', iid=key, text='A long Unicode 🎧 title ' * 5,
                        values=('Published',), number=n+1)
        deck.draw()
        self.assertEqual(tk.Button.call_count, 3)
        deck.draw()
        self.assertEqual(tk.Button.call_count, 3)
        original = deck.buttons['two']
        deck.sync([{'id': 'two', 'label': 'Updated title', 'status': 'Needs attention', 'number': 2},
                   {'id': 'one', 'label': 'First tape', 'status': 'Waiting', 'number': 1},
                   {'id': 'three', 'label': 'Third tape', 'status': 'Published', 'number': 3}])
        self.assertIs(deck.buttons['two'], original)
        self.assertEqual(tk.Button.call_count, 3)
        self.assertEqual(deck.get_children(), ('two', 'one', 'three'))
        deck.choose('one')
        self.assertEqual(deck.selection(), ('one',))
        deck.move('one', -1)
        self.assertEqual(deck.selection(), ('two',))
        deck.buttons['two'].focus_set.assert_called_once()
        self.assertEqual(deck.item('two')['values'], ['Needs attention'])
        deck.delete('one')
        self.assertFalse(deck.exists('one'))
        self.assertEqual(deck.get_children(), ('two', 'three'))

    def test_hatch_acknowledgement_settles_without_touching_publishing(self):
        window = app.Window.__new__(app.Window)
        window.hatch_pulse, window.root, window.draw_drop = 0, Mock(), Mock()
        pending = []
        window.root.after.side_effect = lambda delay, callback: pending.append(callback)
        window.acknowledge_drop()
        self.assertEqual(window.hatch_pulse, 1)
        self.assertEqual(window.hatch_motion, 1)
        while pending:
            pending.pop(0)()
        self.assertEqual(window.hatch_pulse, 0)
        self.assertEqual(window.hatch_motion, 0)
        self.assertEqual(window.draw_drop.call_count, 7)


class QueueTests(AppFixture):
    def test_queue_survives_new_interpreter_and_has_no_credential(self):
        job = p.create_job('file', self.audio)
        script = ('import sys;sys.path.insert(0,sys.argv[1]);import escape_pod_cast as p;'
                  'from pathlib import Path;p.HOME=Path(sys.argv[2]);print(p.load_job(sys.argv[3])["source"])')
        result = subprocess.run([sys.executable, '-c', script, str(Path(p.__file__).parent),
                                 str(self.home), job['id']], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), str(self.audio))
        self.assertNotIn('token', p.job_path(job['id']).read_text())

    def test_url_job_strips_tracking_and_invalid_urls_are_not_queued(self):
        job = p.create_job('youtube', 'https://youtu.be/BaW_jenozKc?si=tracking')
        self.assertEqual(job['source'], 'https://www.youtube.com/watch?v=BaW_jenozKc')
        with self.assertRaises(p.Failure):
            p.create_job('youtube', 'https://example.com')
        self.assertEqual(len(p.list_jobs()), 1)
        with self.assertRaises(p.Failure):
            p.job_path('../../outside')

    def test_stages_success_and_duplicate_workers_run_one_task(self):
        job = p.create_job('file', self.audio)
        stages = []
        def perform(task):
            p.job_progress('Uploading')
            stages.append(p.load_job(job['id'])['stage'])
            self.assertEqual(p.load_job(job['id'])['state'], 'running')
            return 'Published and ready to refresh'
        with patch.object(p, 'perform_job', side_effect=perform) as perform:
            p.run_job(job['id'])
            p.run_job(job['id'])
            self.assertEqual(perform.call_count, 1)
        saved = p.load_job(job['id'])
        self.assertEqual(stages, ['Uploading'])
        self.assertEqual((saved['state'], saved['pid'], saved['attempts']), ('done', None, 1))
        self.assertEqual(self.audio.read_bytes(), b'original')
        self.assertIsNone(p.CURRENT_JOB)

    def test_error_and_retry_retain_source_and_record_real_problem(self):
        job = p.create_job('file', self.audio)
        job['auto_retries'] = len(p.RETRY_DELAYS)
        p.save_job(job)
        with patch.object(p, 'perform_job', side_effect=p.NetworkFailure('The connection timed out.')):
            p.run_job(job['id'])
        failed = p.load_job(job['id'])
        self.assertEqual(failed['state'], 'failed')
        self.assertIn('timed out', failed['error'])
        self.assertIn('Retry', failed['help'])
        p.retry_job(job['id'])
        with patch.object(p, 'perform_job', return_value='success'):
            p.run_job(job['id'])
        self.assertEqual(p.load_job(job['id'])['attempts'], 2)
        self.assertEqual(self.audio.read_bytes(), b'original')

    def test_retry_is_not_blocked_by_an_unrelated_upload(self):
        job = p.create_job('file', self.audio)
        job.update(state='failed', error='network')
        p.save_job(job)
        with p.locked():
            p.retry_job(job['id'])
        self.assertEqual(p.load_job(job['id'])['state'], 'queued')

    def test_queued_cancellation_prevents_publish_without_deleting_audio(self):
        job = p.create_job('file', self.audio)
        p.cancel_job(job['id'])
        with patch.object(p, 'perform_job') as perform:
            p.run_job(job['id'])
            perform.assert_not_called()
        self.assertEqual(p.load_job(job['id'])['state'], 'cancelled')
        self.assertTrue(self.audio.exists())

    def test_running_cancellation_is_refused(self):
        job = p.create_job('file', self.audio)
        with p.job_lock(job['id']):
            with self.assertRaisesRegex(p.Failure, 'already publishing'):
                p.cancel_job(job['id'])

    def test_only_dead_workers_are_marked_interrupted(self):
        job = p.create_job('file', self.audio)
        job.update(state='running', pid=1234567)
        p.save_job(job)
        with patch.object(p.os, 'kill', return_value=None):
            p.recover_jobs()
        self.assertEqual(p.load_job(job['id'])['state'], 'running')
        with patch.object(p.os, 'kill', side_effect=ProcessLookupError()):
            p.recover_jobs()
        self.assertEqual(p.load_job(job['id'])['state'], 'failed')
        self.assertIn('reused', p.load_job(job['id'])['help'])

    def test_maintenance_skips_busy_publisher_without_waiting(self):
        job = p.create_job('file', self.audio)
        with p.locked(), patch.object(p, 'perform_job') as perform:
            p.run_job(job['id'], blocking=False)
            perform.assert_not_called()
        self.assertEqual(p.load_job(job['id'])['state'], 'queued')

    def test_folder_failure_reuses_activity_and_cancel_preserves_original(self):
        inbox = self.home / 'Drop Audio Here'
        inbox.mkdir()
        path = inbox / 'broken.mp3'
        path.write_bytes(b'preserved')
        now = dt.datetime.now(dt.timezone.utc)
        with patch.object(p, 'publish', side_effect=p.Failure('Cannot convert audio format')):
            self.assertEqual(p.process_files(None, None, [path], now, track=True), [path])
            p.process_files(None, None, [path], now, track=True)
        jobs = p.list_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['attempts'], 2)
        p.cancel_job(jobs[0]['id'])
        self.assertFalse(path.exists())
        self.assertEqual((inbox / 'Not Published/broken.mp3').read_bytes(), b'preserved')

    def test_monitor_completes_queued_work_after_window_has_closed(self):
        (self.home / 'config.json').write_text(json.dumps({'repo': 'owner/repo'}))
        job = p.create_job('file', self.audio)
        client = Mock()
        client.assets.return_value = []
        with (patch.object(p, 'perform_job', return_value='success') as perform,
              patch.object(p, 'GitHub', return_value=client),
              patch.object(p, 'get_token', return_value='test'),
              patch.object(sys, 'argv', ['publisher', '--maintain'])):
            p.main()
            perform.assert_called_once()
        self.assertEqual(p.load_job(job['id'])['state'], 'done')

    def test_task_failure_does_not_stop_other_queued_items(self):
        first, second = p.create_job('file', self.audio), p.create_job('check')
        with patch.object(p, 'perform_job', side_effect=[p.Failure('network'), 'connected']):
            p.run_job(first['id'])
            p.run_job(second['id'])
        self.assertEqual([job['state'] for job in p.list_jobs()], ['failed', 'done'])

    def test_invalid_activity_json_is_ignored(self):
        job = p.create_job('check')
        p.job_path(job['id']).write_text('not json')
        self.assertEqual(p.list_jobs(), [])

    def test_current_helpers_are_not_redownloaded_and_old_known_bundles_are_pruned(self):
        home = self.home / 'YouTube Tools'
        home.mkdir()
        def bundle(number, extra=False):
            folder = home / ('bundle-' + str(number) * 16)
            folder.mkdir()
            for filename in ('yt-dlp', 'node', 'Node LICENSE.txt'):
                (folder / filename).write_text('fixture')
                (folder / filename).chmod(0o700)
            if extra:
                (folder / 'my notes.txt').write_text('preserve')
            return folder
        previous, older, user_folder = bundle(1), bundle(2), bundle(3, extra=True)
        tag, filename = '2026.08.19', 'node-v22.23.3-darwin-x64.tar.gz'
        pointer = home / 'active.json'
        pointer.write_text(json.dumps({'bundle': previous.name, 'yt_dlp': tag, 'node': filename}))
        calls = []
        def download(url, path, digest=None, limit=None):
            calls.append(url)
            if url == p.TOOLS_API:
                path.write_text(json.dumps({'tag_name': tag, 'assets': [{
                    'name': 'yt-dlp_macos', 'digest': 'sha256:' + 'b' * 64,
                    'browser_download_url': 'https://github.com/yt-dlp/yt-dlp/releases/download/' + tag + '/yt-dlp_macos'}]}))
            elif url == p.NODE_SUMS:
                path.write_text('a' * 64 + '  ' + filename + '\n')
            else:
                path.write_text('fixture')
        def unpack(archive, filename, folder):
            for name in ('node', 'Node LICENSE.txt'):
                (folder / name).write_text('fixture')
                (folder / name).chmod(0o700)
        with (patch.object(p.sys, 'platform', 'darwin'),
              patch.object(p.platform, 'mac_ver', return_value=('11.7.11', (), '')),
              patch.object(p.platform, 'machine', return_value='x86_64'),
              patch.object(p, 'mac_dialog'), patch.object(p, 'download_tool', side_effect=download),
              patch.object(p, 'unpack_node', side_effect=unpack),
              patch.object(p.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'v22.23.3\n', ''))):
            tools = p.install_youtube_tools()
            self.assertEqual(tools[0].parent, previous)
            self.assertEqual(calls, [p.TOOLS_API, p.NODE_SUMS])
            pointer.write_text(json.dumps({'bundle': previous.name, 'yt_dlp': 'older', 'node': filename}))
            p.install_youtube_tools()
        self.assertTrue(previous.exists())
        self.assertFalse(older.exists())
        self.assertTrue((user_folder / 'my notes.txt').exists())

    def test_two_real_workers_claim_one_queue_item(self):
        job = p.create_job('file', self.audio)
        code = ('import sys,time;from pathlib import Path;'
                'sys.path.insert(0,sys.argv[1]);import escape_pod_cast as p;'
                'p.HOME=Path(sys.argv[2]);'
                'def_placeholder')
        code = code.replace('def_placeholder', '\n'
            'def perform(job):\n'
            '    with (p.HOME/"calls.txt").open("a") as out: out.write("published\\n")\n'
            '    time.sleep(0.15)\n'
            '    return "success"\n'
            'p.perform_job=perform\np.run_job(sys.argv[3])\n')
        args = [sys.executable, '-c', code, str(Path(p.__file__).parent), str(self.home), job['id']]
        workers = [subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        for worker in workers:
            stdout, stderr = worker.communicate(timeout=10)
            self.assertEqual(worker.returncode, 0, stderr.decode())
        self.assertEqual((self.home / 'calls.txt').read_text(), 'published\n')
        self.assertEqual(p.load_job(job['id'])['attempts'], 1)

    def test_worker_command_uses_argument_list_and_separate_process(self):
        job = p.create_job('file', self.audio)
        with patch.object(app.subprocess, 'Popen') as popen:
            app.launch_worker(job)
        args = popen.call_args.args[0]
        self.assertEqual(args[-2:], ['--job', job['id']])
        self.assertTrue(popen.call_args.kwargs['start_new_session'])
        self.assertNotIn('shell', popen.call_args.kwargs)


class UpdateTests(unittest.TestCase):
    def test_setup_receipt_is_written_only_after_success(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            result = home / 'result.json'
            config = {'repo': 'owner/show', 'feed_url': 'https://owner.github.io/show/feed.xml'}
            with (patch.object(install.sys, 'platform', 'darwin'),
                  patch.object(p, 'CONFIG', home / 'config.json'),
                  patch.object(install, 'choose_window_runtime'),
                  patch.object(install, 'choose_repository', return_value='owner/show'),
                  patch.object(install, 'connect', return_value=config),
                  patch.object(install, 'install_app'), patch.object(install, 'notify'),
                  patch.object(install.subprocess, 'run'),
                  patch.object(p, 'public_bytes', return_value=b'<rss><channel/></rss>'),
                  patch.object(install, 'dialog', return_value=('Done', ''))):
                install.main(result)
            self.assertEqual(json.loads(result.read_text()), {'installed': True})
            result.unlink()
            with (patch.object(install.sys, 'platform', 'darwin'),
                  patch.object(install, 'choose_window_runtime', side_effect=install.Cancelled())):
                with self.assertRaises(install.Cancelled):
                    install.main(result)
            self.assertFalse(result.exists())

    def test_failed_native_compile_leaves_existing_app_and_script(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            target = home / 'Applications/Escape Pod Cast.app'
            target.mkdir(parents=True)
            (target / 'keep.txt').write_text('old app')
            runtime = home / 'support'
            runtime.mkdir()
            (runtime / 'escape_pod_cast.py').write_text('old script')
            def run(args, **kwargs):
                if args[0] == '/usr/bin/osacompile':
                    raise subprocess.CalledProcessError(1, args)
                return subprocess.CompletedProcess(args, 0)
            with (patch.object(install, 'HOME', runtime), patch.object(install, 'APP', target),
                  patch.object(install.subprocess, 'run', side_effect=run)):
                with self.assertRaises(subprocess.CalledProcessError):
                    install.install_app({'feed_url': 'https://feed'})
            self.assertEqual((target / 'keep.txt').read_text(), 'old app')
            self.assertEqual((runtime / 'escape_pod_cast.py').read_text(), 'old script')

    def test_missing_window_toolkit_has_explicit_native_fallback_choice(self):
        with (patch.object(install, 'window_support', return_value=False),
              patch.object(install, 'dialog', return_value=('Use Simple App', '')),
              patch.object(install.subprocess, 'run') as run):
            install.choose_window_runtime()
            run.assert_not_called()
        with (patch.object(install, 'window_support', return_value=False),
              patch.object(install, 'dialog', return_value=('Get Python', '')),
              patch.object(install.subprocess, 'run') as run):
            with self.assertRaises(install.Cancelled):
                install.choose_window_runtime()
            self.assertEqual(run.call_args.args[0][-1], 'https://www.python.org/downloads/macos/')

    def test_update_extracts_only_known_files_from_pinned_commit(self):
        sha = 'a' * 40
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            def curl(args, **kwargs):
                with zipfile.ZipFile(folder / 'update.zip', 'w') as archive:
                    for file in app.UPDATE_FILES:
                        archive.writestr('Escape-Pod-Cast-' + sha + '/' + file, '# approved app fixture')
                    archive.writestr('../../evil.py', 'malicious ignored file')
                self.assertIn('/archive/' + sha + '.zip', args[-1])
                self.assertNotIn('--insecure', args)
                return subprocess.CompletedProcess(args, 0)
            with (patch.object(app.sys, 'platform', 'darwin'),
                  patch.object(p, 'mac_transfer', return_value=(200, json.dumps({'object': {'sha': sha}}).encode(), {})),
                  patch.object(app.subprocess, 'run', side_effect=curl)):
                result = app.fetch_update(folder, lambda text: None)
            self.assertEqual(result, folder / 'mac/install.py')
            self.assertFalse((folder / 'evil.py').exists())
            self.assertTrue(all((folder / file).exists() for file in app.UPDATE_FILES))

    def test_missing_update_file_refuses_install(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            def curl(args, **kwargs):
                with zipfile.ZipFile(folder / 'update.zip', 'w') as archive:
                    archive.writestr('other.py', 'wrong archive')
                return subprocess.CompletedProcess(args, 0)
            with (patch.object(app.sys, 'platform', 'darwin'),
                  patch.object(p, 'mac_transfer', return_value=(200, json.dumps({'object': {'sha': 'a' * 40}}).encode(), {})),
                  patch.object(app.subprocess, 'run', side_effect=curl)):
                with self.assertRaisesRegex(p.Failure, 'Nothing was installed'):
                    app.fetch_update(folder, lambda text: None)

    def test_repository_field_accepts_browser_link_without_accepting_other_hosts(self):
        for value in ('owner/show', 'https://github.com/owner/show/', 'https://github.com/owner/show.git'):
            self.assertEqual(install.repository_name(value), 'owner/show')
        for value in ('https://github.com.evil/owner/show', 'https://secret@github.com/owner/show',
                      'https://github.com/owner/show/tree/main', 'https://github.com/owner/show?token=secret'):
            with self.assertRaises(ValueError):
                install.repository_name(value)

    def test_droplet_uses_window_when_available_and_keeps_native_fallback(self):
        script = install.droplet_source('/python', '/publisher.py', '/drop', '/log', 'https://feed')
        self.assertIn('my runWindow({})', script)
        self.assertIn('my runWindow(argumentsList)', script)
        self.assertIn('/app.py', script)
        self.assertIn('tkinter.TkVersion >= 8.6', script)
        self.assertIn('choose from list', script)
        self.assertIn('quoted form of (argumentText as text)', script)


@unittest.skipUnless(os.environ.get('DISPLAY') or (sys.platform == 'darwin' and os.environ.get('EPC_MAC_GUI_TESTS')),
                     'GUI checks need a display or EPC_MAC_GUI_TESTS=1 in an interactive Mac session')
class WindowTests(AppFixture):
    def setUp(self):
        super().setUp()
        import tkinter as tk
        from tkinter import ttk
        self.root = tk.Tk()
        self.dialogs = {'file': Mock(), 'message': Mock()}
        self.worker = patch.object(app, 'launch_worker', return_value=Mock(poll=Mock(return_value=None)))
        self.worker.start()
        self.addCleanup(self.worker.stop)
        self.window = app.Window(self.root, tk, ttk, self.dialogs)
        self.root.update()
        self.addCleanup(self.root.destroy)

    def test_window_input_error_retry_and_small_layout(self):
        self.window.link.set('https://youtu.be/BaW_jenozKc')
        self.window.add_youtube()
        self.window.refresh()
        self.root.update()
        job = p.list_jobs()[0]
        self.assertIn(job['id'], self.window.table.get_children())
        self.assertEqual(self.window.link.get(), '')
        job.update(state='failed', stage='Needs attention', error='Network unavailable', help='Check connection and Retry')
        p.save_job(job)
        self.window.selected = job['id']
        self.window.refresh()
        self.root.update()
        self.assertIn('Retry', self.window.explanation.get())
        self.assertFalse(self.window.retry.instate(['disabled']))
        self.window.retry_selected()
        self.assertEqual(p.load_job(job['id'])['state'], 'queued')
        self.root.geometry('650x560')
        self.root.update()
        self.assertLess(self.window.remove.winfo_rooty(), self.root.winfo_rooty() + self.root.winfo_height())

    def test_invalid_link_does_not_crash_or_queue(self):
        self.window.link.set('not a video')
        self.window.add_youtube()
        self.dialogs['message'].showerror.assert_called_once()
        self.assertEqual(p.list_jobs(), [])

    def test_cancelled_and_completed_rows_have_working_details(self):
        job = p.create_job('file', self.audio)
        p.cancel_job(job['id'])
        self.window.selected = job['id']
        self.window.refresh()
        self.root.update()
        self.assertIn('No original', self.window.explanation.get())
        self.assertEqual(self.window.table.item(job['id'])['values'], ['Removed'])
        self.assertTrue(self.window.retry.instate(['disabled']))

    def test_radio_layout_and_tape_selection_at_minimum_window_size(self):
        self.root.geometry('650x680')
        job = p.create_job('file', self.audio)
        self.window.refresh()
        self.root.update()
        self.window.table.choose(job['id'])
        self.assertEqual(self.window.selected, job['id'])
        self.assertIn(self.audio.name, self.window.explanation.get())
        self.assertGreaterEqual(self.window.table.canvas.winfo_height(), 84)
        bottom = self.window.privacy_label.winfo_rooty() + self.window.privacy_label.winfo_height()
        self.assertLessEqual(bottom, self.root.winfo_rooty() + self.root.winfo_height())


if __name__ == '__main__':
    unittest.main()
