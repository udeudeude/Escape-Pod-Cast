import copy
import datetime as dt
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

SPEC = importlib.util.spec_from_file_location('publisher', Path(__file__).parents[1] / 'mac/escape_pod_cast.py')
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)
NOW = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)


def feed():
    return ET.parse(Path(__file__).parents[1] / 'docs/feed.xml').getroot()


def asset(name='epc-' + 'a' * 64 + '.mp3', age=0):
    return {'id': 1, 'name': name, 'created_at': (NOW - dt.timedelta(days=age)).isoformat(),
            'browser_download_url': 'https://github.com/example/audio/' + name,
            'size': 20, 'content_type': 'audio/mpeg', 'state': 'uploaded'}


class FakeClient:
    def __init__(self):
        self.root, self.media, self.deleted = feed(), [], []
        self.writes, self.uploads = 0, 0
        self.fail_write = False

    def assets(self, release):
        return copy.deepcopy(self.media)

    def read_feed(self):
        return copy.deepcopy(self.root), 'current-sha'

    def write_feed(self, root, sha):
        if self.fail_write:
            raise p.Failure('Concurrent update or network failure')
        self.root = copy.deepcopy(root)
        self.writes += 1

    def upload(self, release, path, name, mime):
        self.uploads += 1
        result = asset(name)
        result.update(id=self.uploads, size=path.stat().st_size, content_type=mime)
        self.media.append(result)
        return result

    def request(self, method, path):
        if method == 'DELETE':
            self.deleted.append(path)
            self.media = [a for a in self.media if str(a['id']) != path.rsplit('/', 1)[1]]


class FeedTests(unittest.TestCase):
    def test_xml_escaping_and_enclosure(self):
        root = feed()
        p.add_episode(root, asset(), 'Rock & <Roll> "mix"', NOW)
        restored = ET.fromstring(ET.tostring(root))
        item = p.channel(restored).find('item')
        self.assertEqual(item.findtext('title'), 'Rock & <Roll> "mix"')
        self.assertEqual(item.find('enclosure').attrib['length'], '20')
        self.assertEqual(item.find('enclosure').attrib['type'], 'audio/mpeg')
        self.assertEqual(p.channel(root).findtext('{%s}block' % p.NS), 'Yes')

    def test_guid_deduplicates(self):
        root = feed()
        self.assertTrue(p.add_episode(root, asset(), 'first', NOW))
        self.assertFalse(p.add_episode(root, asset(), 'renamed', NOW))
        self.assertEqual(len(p.channel(root).findall('item')), 1)

    def test_malformed_channel(self):
        with self.assertRaises(p.Failure):
            p.channel(ET.fromstring('<rss/>'))


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.source = Path(self.temp.name) / 'my audio.mp3'
        self.source.write_bytes(b'mp3 test bytes')
        self.client = FakeClient()
        self.audio = patch.object(p, 'prepare_audio', side_effect=lambda path, _: (path, '.mp3', 'audio/mpeg'))
        self.check = patch.object(p, 'verify_enclosure')
        self.audio.start()
        self.check.start()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.audio.stop)
        self.addCleanup(self.check.stop)

    def test_retry_after_feed_failure_reuses_audio(self):
        self.client.fail_write = True
        with self.assertRaises(p.Failure):
            p.publish(self.client, {}, self.source, NOW)
        self.assertEqual(self.client.uploads, 1)
        self.assertEqual(self.client.writes, 0)
        self.client.fail_write = False
        p.publish(self.client, {}, self.source, NOW)
        self.assertEqual(self.client.uploads, 1)
        self.assertEqual(self.client.writes, 1)
        self.assertEqual(self.source.read_bytes(), b'mp3 test bytes')

    def test_duplicate_drop_has_one_episode(self):
        p.publish(self.client, {}, self.source, NOW)
        p.publish(self.client, {}, self.source, NOW)
        self.assertEqual(self.client.uploads, 1)
        self.assertEqual(self.client.writes, 1)

    def test_expired_duplicate_gets_new_lifetime_and_guid(self):
        p.publish(self.client, {}, self.source, NOW)
        first_guid = p.channel(self.client.root).find('item').findtext('guid')
        future = NOW + dt.timedelta(days=15)
        p.publish(self.client, {}, self.source, future)
        self.assertEqual(self.client.uploads, 2)
        items = p.channel(self.client.root).findall('item')
        self.assertEqual(len(items), 1)
        self.assertNotEqual(items[0].findtext('guid'), first_guid)

    def test_bad_range_does_not_publish(self):
        with patch.object(p, 'verify_enclosure', side_effect=p.Failure('bad range')):
            with self.assertRaises(p.Failure):
                p.publish(self.client, {}, self.source, NOW)
        self.assertEqual(self.client.writes, 0)

    def test_changed_file_rejected_before_upload(self):
        original_copy = shutil.copyfile

        def changing(source, target):
            original_copy(source, target)
            source.write_bytes(b'changed source with different size')

        with patch.object(p.shutil, 'copyfile', side_effect=changing):
            with self.assertRaises(p.Failure):
                p.publish(self.client, {}, self.source, NOW)
        self.assertEqual(self.client.uploads, 0)

    def test_one_bad_file_does_not_block_other_files(self):
        missing = self.source.with_name('missing.mp3')
        failed = p.process_files(self.client, {}, [missing, self.source], NOW)
        self.assertEqual(failed, [missing])
        self.assertEqual(self.client.writes, 1)


class CleanupTests(unittest.TestCase):
    def test_only_owned_expired_assets(self):
        client = FakeClient()
        old, fresh, unrelated = asset(age=14), asset('epc-' + 'b' * 64 + '.m4a', age=13), asset('other.mp3', age=100)
        fresh['id'], unrelated['id'] = 2, 3
        client.media = [old, fresh, unrelated]
        for a in client.media:
            p.add_episode(client.root, a, a['name'], NOW)
        p.cleanup(client, {}, NOW)
        self.assertEqual(client.deleted, ['/releases/assets/1'])
        self.assertEqual(len(p.channel(client.root).findall('item')), 2)

    def test_failed_feed_update_preserves_audio(self):
        client = FakeClient()
        client.media = [asset(age=15)]
        p.add_episode(client.root, client.media[0], 'old', NOW)
        client.fail_write = True
        with self.assertRaises(p.Failure):
            p.cleanup(client, {}, NOW)
        self.assertEqual(client.deleted, [])

    def test_orphaned_old_upload_deleted(self):
        client = FakeClient()
        client.media = [asset(age=15)]
        p.cleanup(client, {}, NOW)
        self.assertEqual(client.writes, 0)
        self.assertEqual(client.deleted, ['/releases/assets/1'])


class Response:
    def __init__(self, status=206, headers=None, payload=b'x'):
        self.status = status
        self.headers = headers or {}
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, n):
        return self.payload[:n]


class DeliveryTests(unittest.TestCase):
    def test_real_partial_response_required(self):
        head = Response(200, {'Content-Length': '20'})
        partial = Response(206, {'Content-Range': 'bytes 0-0/20'})
        with patch.object(p.urllib.request, 'urlopen', side_effect=[head, partial]) as request:
            p.verify_enclosure('https://example.com/audio', 20)
        self.assertEqual(request.call_args_list[0].args[0].method, 'HEAD')
        self.assertEqual(request.call_args_list[1].args[0].headers['Range'], 'bytes=0-0')
        self.assertNotIn('Authorization', request.call_args_list[1].args[0].headers)

    def test_200_instead_of_206_is_rejected(self):
        responses = [Response(200, {'Content-Length': '20'}), Response(200)]
        with patch.object(p.urllib.request, 'urlopen', side_effect=responses):
            with self.assertRaises(p.Failure):
                p.verify_enclosure('https://example.com/audio', 20)

    def test_wrong_head_size_is_rejected(self):
        with patch.object(p.urllib.request, 'urlopen', return_value=Response(200, {'Content-Length': '21'})):
            with self.assertRaises(p.Failure):
                p.verify_enclosure('https://example.com/audio', 20)

    def test_pagination(self):
        client = p.GitHub('a/b', 'fake-token')
        with patch.object(client, 'request', side_effect=[[asset()] * 100, [asset()]]) as request:
            self.assertEqual(len(client.assets({'id': 1})), 101)
        self.assertIn('page=2', request.call_args_list[1].args[1])


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg unavailable')
class ConversionTests(unittest.TestCase):
    def test_wav_converts_and_aac_passes_through(self):
        import wave
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            source = directory / 'tone.wav'
            with wave.open(str(source), 'wb') as wav:
                wav.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
                wav.writeframes(b'\0\0' * 44100)
            media, suffix, mime = p.prepare_audio(source, directory)
            self.assertEqual((suffix, mime), ('.m4a', 'audio/mp4'))
            self.assertGreater(media.stat().st_size, 0)
            self.assertEqual(p.prepare_audio(media, directory)[0], media)

    def test_lossless_m4a_is_converted(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            source = directory / 'lossless.m4a'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'anullsrc=r=44100:cl=mono', '-t', '0.2', '-c:a',
                            'alac', str(source)], check=True)
            media, _, _ = p.prepare_audio(source, directory)
            self.assertNotEqual(media, source)

    def test_empty_file_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'empty.mp3'
            source.touch()
            with self.assertRaises(p.Failure):
                p.prepare_audio(source, Path(folder))


if __name__ == '__main__':
    unittest.main()
