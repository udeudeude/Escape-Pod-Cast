"""YouTube boundaries: canonical links, compatible tools, retry-safe publication."""
import copy
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parents[1] / 'mac'))
import escape_pod_cast as p
import install as installer

VIDEO = 'BaW_jenozKc'
URL = 'https://www.youtube.com/watch?v=' + VIDEO
NOW = dt.datetime(2026, 10, 5, tzinfo=dt.timezone.utc)


class LinkTests(unittest.TestCase):
    def test_common_links_become_single_tracking_free_video(self):
        for value in (URL + '&list=ignore&t=21', 'https://youtu.be/' + VIDEO + '?si=tracking',
                      'https://m.youtube.com/watch?v=' + VIDEO,
                      'https://music.youtube.com/watch?v=' + VIDEO,
                      'https://youtube.com/shorts/' + VIDEO,
                      'https://www.youtube.com/live/' + VIDEO,
                      'http://youtube.com/embed/' + VIDEO + '/'):
            with self.subTest(value=value):
                self.assertEqual(p.youtube_url(value), (URL, VIDEO))

    def test_rejects_other_hosts_schemes_credentials_ports_and_nonvideos(self):
        for value in ('file:///etc/passwd', 'https://youtube.com.evil/watch?v=' + VIDEO,
                      'https://evil@youtube.com/watch?v=' + VIDEO,
                      'https://youtube.com:443/watch?v=' + VIDEO,
                      'https://youtube.com/playlist?list=123', 'https://youtube.com/@channel',
                      URL + '&v=' + VIDEO, 'https://youtu.be/short', '-o /tmp/a',
                      URL + '\n' + URL, 'https://youtu.be/' + VIDEO + '/extra'):
            with self.subTest(value=value), self.assertRaises(p.Failure):
                p.youtube_url(value)

    def test_link_files_including_binary_webloc_and_unicode_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for suffix, payload in (
                    ('.webloc', plistlib.dumps({'URL': URL}, fmt=plistlib.FMT_BINARY)),
                    ('.url', ('[InternetShortcut]\r\nURL=' + URL + '\r\n').encode()),
                    ('.txt', ('\ufeff' + URL + '\n').encode())):
                path = directory / ('🎧 saved link' + suffix)
                path.write_bytes(payload)
                self.assertEqual(p.link_file(path), URL)
            path.write_text('two links\n' + URL)
            with self.assertRaises(p.Failure):
                p.link_file(path)

    def test_oversize_link_and_nonstring_webloc_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'bad.webloc'
            path.write_bytes(plistlib.dumps({'URL': 123}))
            with self.assertRaises(p.Failure):
                p.link_file(path)
            path.write_bytes(b'x' * (64 * 1024 + 1))
            with self.assertRaises(p.Failure):
                p.link_file(path)


class HelperTests(unittest.TestCase):
    def test_node22_download_is_pinned_to_major_and_machine(self):
        sums = '\n'.join('a' * 64 + '  node-v22.23.3-darwin-' + arch + '.tar.gz'
                         for arch in ('x64', 'arm64'))
        for machine, arch in (('x86_64', 'x64'), ('arm64', 'arm64')):
            url, digest, filename = p.node_download(sums, machine)
            self.assertIn('/v22.23.3/', url)
            self.assertEqual(filename, 'node-v22.23.3-darwin-' + arch + '.tar.gz')
            self.assertEqual(digest, 'a' * 64)
        for bad in ('a' * 64 + '  node-v24.1.0-darwin-x64.tar.gz', sums + '\n' + sums):
            with self.assertRaises(p.Failure):
                p.node_download(bad, 'x86_64')

    def test_checksum_failure_prevents_executing_download(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / 'tool'
            def fake_run(args, **kwargs):
                destination.write_bytes(b'corrupt download')
                self.assertIn('--proto-redir', args)
                self.assertNotIn('--insecure', args)
                self.assertNotIn('Authorization', ' '.join(args))
                return subprocess.CompletedProcess(args, 0, '', '')
            with patch.object(p.subprocess, 'run', side_effect=fake_run):
                with self.assertRaisesRegex(p.Failure, 'safety check'):
                    p.download_tool('https://nodejs.org/download/release/v22.1.0/file',
                                    destination, 'a' * 64)

    def test_node_extracts_only_fixed_regular_members(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            filename = 'node-v22.23.3-darwin-x64.tar.gz'
            archive = folder / filename
            root = filename[:-7]
            for symlink in (False, True):
                with tarfile.open(archive, 'w:gz') as bundle:
                    for name in (root + '/bin/node', root + '/LICENSE', '../../escaped'):
                        member = tarfile.TarInfo(name)
                        payload = b'fixture'
                        if symlink and name.endswith('/bin/node'):
                            member.type, member.linkname = tarfile.SYMTYPE, '/etc/passwd'
                            bundle.addfile(member)
                        else:
                            member.size = len(payload)
                            bundle.addfile(member, io.BytesIO(payload))
                if symlink:
                    with self.assertRaises(p.Failure):
                        p.unpack_node(archive, filename, folder)
                else:
                    p.unpack_node(archive, filename, folder)
                    self.assertEqual((folder / 'node').read_bytes(), b'fixture')
                    self.assertEqual((folder / 'node').stat().st_mode & 0o777, 0o700)
                self.assertFalse((folder / 'escaped').exists())

    def test_bundle_pointer_cannot_escape_private_folder(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(p, 'HOME', Path(temp)):
            home = Path(temp) / 'YouTube Tools'
            home.mkdir()
            (home / 'active.json').write_text(json.dumps({'bundle': '../../other'}))
            self.assertIsNone(p.active_youtube_tools())

    def test_installer_works_on_both_macos_versions_and_keeps_old_on_failure(self):
        for version in ('11.7.11', '15.7'):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temp:
                home = Path(temp)
                tools = home / 'YouTube Tools'
                old = tools / ('bundle-' + '0' * 16)
                old.mkdir(parents=True)
                for name in ('node', 'yt-dlp'):
                    (old / name).write_text('old working tool')
                    (old / name).chmod(0o700)
                pointer = tools / 'active.json'
                previous = json.dumps({'bundle': old.name})
                pointer.write_text(previous)
                def download(url, path, digest=None, limit=None):
                    if url == p.TOOLS_API:
                        path.write_text(json.dumps({'tag_name': '2026.08.19', 'assets': [{
                            'name': 'yt-dlp_macos', 'digest': 'sha256:' + 'b' * 64,
                            'browser_download_url': 'https://github.com/yt-dlp/yt-dlp/releases/download/x/yt-dlp_macos'}]}))
                    elif url == p.NODE_SUMS:
                        path.write_text('a' * 64 + '  node-v22.23.3-darwin-x64.tar.gz\n')
                    else:
                        path.write_bytes(b'fixture')
                def unpack(archive, filename, directory):
                    for name in ('node', 'Node LICENSE.txt'):
                        (directory / name).write_text('fixture')
                        (directory / name).chmod(0o700)
                with (patch.object(p, 'HOME', home), patch.object(p.sys, 'platform', 'darwin'),
                      patch.object(p.platform, 'mac_ver', return_value=(version, (), '')),
                      patch.object(p.platform, 'machine', return_value='x86_64'),
                      patch.object(p, 'mac_dialog'), patch.object(p, 'download_tool', side_effect=download),
                      patch.object(p, 'unpack_node', side_effect=unpack),
                      patch.object(p.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'bad'))):
                    with self.assertRaises(p.Failure):
                        p.install_youtube_tools()
                    self.assertEqual(pointer.read_text(), previous)
                    self.assertEqual((old / 'node').read_text(), 'old working tool')
                with (patch.object(p, 'HOME', home), patch.object(p.sys, 'platform', 'darwin'),
                      patch.object(p.platform, 'mac_ver', return_value=(version, (), '')),
                      patch.object(p.platform, 'machine', return_value='x86_64'),
                      patch.object(p, 'mac_dialog'), patch.object(p, 'download_tool', side_effect=download),
                      patch.object(p, 'unpack_node', side_effect=unpack),
                      patch.object(p.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'v22.23.3\n', ''))):
                    result = p.install_youtube_tools()
                    self.assertNotEqual(json.loads(pointer.read_text())['bundle'], old.name)
                    self.assertTrue(all(path.exists() for path in result))

    def test_helper_environment_does_not_inject_external_code(self):
        with patch.dict(p.os.environ, {'NODE_OPTIONS': '--require evil', 'PYTHONPATH': '/evil'}):
            env = p.tool_environment()
        self.assertNotIn('NODE_OPTIONS', env)
        self.assertNotIn('PYTHONPATH', env)


class DownloadTests(unittest.TestCase):
    def test_arguments_safe_and_title_from_metadata_not_filename(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            def run(args, **kwargs):
                self.assertEqual(args[-2:], ['--', URL])
                for flag in ('--ignore-config', '--no-plugin-dirs', '--no-playlist',
                             '--no-remote-components', '--abort-on-unavailable-fragments'):
                    self.assertIn(flag, args)
                self.assertIn('node:/private tools/node', args)
                self.assertNotIn('--cookies-from-browser', args)
                self.assertNotIn('shell', kwargs)
                (folder / 'audio.m4a').write_bytes(b'aac fixture')
                (folder / 'audio.info.json').write_text(json.dumps({
                    'id': VIDEO, 'title': 'Rock & <Roll> / $(not executed)\u0001'}))
                return subprocess.CompletedProcess(args, 0)
            with patch.object(p.subprocess, 'run', side_effect=run):
                media, title = p.download_youtube(URL, VIDEO, folder,
                                                 (Path('/private tools/yt-dlp'), Path('/private tools/node')))
                self.assertEqual(media.name, 'audio.m4a')
                self.assertEqual(title, 'Rock & <Roll> / $(not executed)')

    def test_empty_wrong_live_and_skipped_downloads_fail(self):
        for metadata in ({'id': VIDEO, 'title': 'test', 'is_live': True},
                         {'id': 'different', 'title': 'test'}, {'id': VIDEO, 'title': ''}):
            with tempfile.TemporaryDirectory() as temp:
                folder = Path(temp)
                (folder / 'audio.info.json').write_text(json.dumps(metadata))
                (folder / 'audio.m4a').write_bytes(b'fixture')
                with patch.object(p.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
                    with self.assertRaises(p.Failure):
                        p.download_youtube(URL, VIDEO, folder, (Path('yt-dlp'), Path('node')))
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(p.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
                with self.assertRaises(p.Failure):
                    p.download_youtube(URL, VIDEO, Path(temp), (Path('yt-dlp'), Path('node')))


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.root, self.media, self.uploads, self.writes = p.new_feed(), [], 0, 0
        self.fail_write = False
        self.tools = patch.object(p, 'active_youtube_tools', return_value=(Path('yt-dlp'), Path('node')))
        self.audio = patch.object(p, 'prepare_audio', side_effect=lambda path, _: (path, '.m4a', 'audio/mp4'))
        self.check = patch.object(p, 'verify_enclosure')
        for mock in (self.tools, self.audio, self.check):
            mock.start()
            self.addCleanup(mock.stop)

    def assets(self, release):
        return copy.deepcopy(self.media)

    def read_feed(self):
        return copy.deepcopy(self.root), 'sha'

    def write_feed(self, root, sha):
        if self.fail_write:
            raise p.Failure('feed write failed')
        self.root, self.writes = copy.deepcopy(root), self.writes + 1

    def upload(self, release, path, name, mime, label=None):
        self.uploads += 1
        asset = {'id': self.uploads, 'name': name, 'label': label,
                 'created_at': NOW.isoformat(), 'state': 'uploaded', 'size': path.stat().st_size,
                 'browser_download_url': 'https://example.com/audio/' + name, 'content_type': mime}
        self.media.append(asset)
        return asset

    def download(self, url, video, directory, tools):
        media = directory / 'audio.m4a'
        media.write_bytes(b'fixture audio')
        return media, 'A title & <symbols>'

    def test_duplicate_links_and_feed_retry_reuse_audio_and_title(self):
        with patch.object(p, 'download_youtube', side_effect=self.download) as download:
            self.fail_write = True
            with self.assertRaises(p.Failure):
                p.publish_youtube(self, {}, URL, NOW)
            self.fail_write = False
            p.publish_youtube(self, {}, 'https://youtu.be/' + VIDEO, NOW)
            p.publish_youtube(self, {}, URL + '&t=20', NOW)
            self.assertEqual(download.call_count, 1)
        self.assertEqual(self.uploads, 1)
        self.assertEqual(self.writes, 1)
        self.assertEqual(p.channel(self.root).find('item').findtext('title'), 'A title & <symbols>')
        digest = hashlib.sha256(('youtube:' + VIDEO).encode()).hexdigest()
        self.assertEqual(self.media[0]['name'], 'epc-' + digest + '.m4a')

    def test_failed_download_does_not_upload_or_change_feed(self):
        with patch.object(p, 'download_youtube', side_effect=p.Failure('network')):
            with self.assertRaises(p.Failure):
                p.publish_youtube(self, {}, URL, NOW)
        self.assertEqual((self.uploads, self.writes), (0, 0))

    def test_monitor_does_not_open_install_prompts(self):
        with patch.object(p, 'active_youtube_tools', return_value=None), patch.object(p, 'install_youtube_tools') as setup:
            with self.assertRaisesRegex(p.Failure, 'Set up / update'):
                p.publish_youtube(self, {}, URL, NOW, prompt=False)
            setup.assert_not_called()

    def test_bad_links_leave_originals_and_batch_continues(self):
        with tempfile.TemporaryDirectory() as temp:
            bad, good = Path(temp) / 'bad.txt', Path(temp) / 'good.webloc'
            bad.write_text('https://not-youtube.example/audio')
            good.write_bytes(plistlib.dumps({'URL': URL}))
            with patch.object(p, 'download_youtube', side_effect=self.download):
                self.assertEqual(p.process_files(self, {}, [bad, good], NOW), [bad])
            self.assertTrue(good.exists())
            self.assertEqual(self.uploads, 1)


class AppTests(unittest.TestCase):
    def test_paste_saved_drop_and_helper_update_actions(self):
        script = installer.droplet_source('/python', '/publisher', '/drop', '/log', 'https://feed')
        for value in ('Paste YouTube link…', 'Set up / update YouTube…', 'on open location',
                      'my runPublisher({"--youtube", text returned of answer})',
                      'my runPublisher({"--youtube-setup"})', 'quoted form of (argumentText as text)'):
            self.assertIn(value, script)

    def test_cli_preserves_url_and_folder_links_move_only_after_success(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            config = home / 'config.json'
            config.write_text(json.dumps({'repo': 'owner/repo'}))
            inbox = home / 'Drop Audio Here'
            inbox.mkdir()
            good, bad = inbox / 'good.webloc', inbox / 'bad.txt'
            good.write_bytes(plistlib.dumps({'URL': URL}))
            bad.write_text('not a link')
            for path in (good, bad):
                p.os.utime(path, (1, 1))
            client = Mock()
            client.assets.return_value = []
            with (patch.object(p, 'HOME', home), patch.object(p, 'CONFIG', config),
                  patch.object(p, 'GitHub', return_value=client),
                  patch.object(p, 'get_token', return_value='test'),
                  patch.object(p, 'publish_youtube') as publish,
                  patch.object(sys, 'argv', ['publisher', '--youtube', URL])):
                p.main()
                self.assertEqual(publish.call_args.args[2], URL)
                publish.reset_mock()
                with patch.object(sys, 'argv', ['publisher', '--maintain']):
                    with self.assertRaisesRegex(p.Failure, '1 item'):
                        p.main()
                self.assertFalse(publish.call_args.kwargs['prompt'])
                self.assertTrue((inbox / 'Published/good.webloc').exists())
                self.assertTrue(bad.exists())
                self.assertFalse(good.exists())

    def test_helper_setup_does_not_require_github_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            with (patch.object(p, 'HOME', home), patch.object(p, 'CONFIG', home / 'missing.json'),
                  patch.object(p, 'install_youtube_tools') as setup,
                  patch.object(p, 'GitHub') as github,
                  patch.object(sys, 'argv', ['publisher', '--youtube-setup'])):
                p.main()
                setup.assert_called_once()
                github.assert_not_called()
