"""Native curl transport checks without credentials or real GitHub mutations."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'mac'))
import escape_pod_cast as p
import install as installer


class MacTransferTests(unittest.TestCase):
    def response(self, status=200, body=b'{}', headers='HTTP/2 200\r\nContent-Length: 2\r\n\r\n'):
        def fake_run(args, **kwargs):
            Path(args[args.index('--output') + 1]).write_bytes(body)
            Path(args[args.index('--dump-header') + 1]).write_text(headers)
            return subprocess.CompletedProcess(args, 0, str(status), '')
        return fake_run

    def test_authentication_stays_in_stdin_and_local_curl_config_is_disabled(self):
        with patch.object(p.subprocess, 'run', side_effect=self.response()) as run:
            p.mac_transfer('https://api.github.com/repos/owner/show',
                           headers={'Authorization': 'Bearer github_pat_secret'})
        args = run.call_args.args[0]
        self.assertEqual(args[:2], ['/usr/bin/curl', '-q'])
        self.assertNotIn('github_pat_secret', ' '.join(args))
        self.assertIn('Authorization: Bearer github_pat_secret', run.call_args.kwargs['input'])
        self.assertNotIn('--location', args)  # Authenticated API calls do not redirect.

    def test_json_api_uses_native_transport_and_preserves_http_errors(self):
        with (patch.object(p.sys, 'platform', 'darwin'),
              patch.object(p, 'mac_transfer', return_value=(404, b'{}', {}))):
            client = p.GitHub('owner/show', 'fake')
            self.assertIsNone(client.request('GET', '/pages', missing=True))
            with self.assertRaisesRegex(p.Failure, '404'):
                client.request('GET', '/pages')

    def test_final_headers_after_redirects(self):
        headers = ('HTTP/1.1 302 Found\r\nContent-Length: 99\r\nOld-Header: old\r\n\r\n'
                   'HTTP/2 206\r\nContent-Length: 1\r\nContent-Range: bytes 0-0/20\r\n\r\n')
        with patch.object(p.subprocess, 'run', side_effect=self.response(206, b'x', headers)):
            status, data, result = p.mac_transfer('https://github.com/audio', follow=True)
        self.assertEqual((status, data), (206, b'x'))
        self.assertEqual(result['content-length'], '1')
        self.assertNotIn('old-header', result)

    def test_dns_error_is_readable_and_credential_is_not_exposed(self):
        failed = subprocess.CompletedProcess([], 6, '000', 'some sensitive diagnostic text')
        with patch.object(p.subprocess, 'run', return_value=failed):
            with self.assertRaises(p.NetworkFailure) as error:
                p.mac_transfer('https://api.github.com', headers={'Authorization': 'secret'})
        self.assertIn('server address', str(error.exception))
        self.assertNotIn('sensitive', str(error.exception))
        self.assertNotIn('secret', str(error.exception))

    def test_audio_upload_streams_file_with_post(self):
        release = {'upload_url': 'https://uploads.github.com/repos/o/r/releases/1/assets{?name,label}'}
        result = {'id': 1}
        with (patch.object(p.sys, 'platform', 'darwin'),
              patch.object(p, 'mac_transfer', return_value=(201, json.dumps(result).encode(), {})) as transfer):
            actual = p.GitHub('o/r', 'secret').upload(release, Path('/tmp/audio.mp3'), 'audio.mp3', 'audio/mpeg')
        self.assertEqual(actual, result)
        self.assertEqual(transfer.call_args.args[1], 'POST')
        self.assertEqual(transfer.call_args.kwargs['upload'], Path('/tmp/audio.mp3'))

    def test_head_and_real_partial_response_are_required_without_auth(self):
        responses = [(200, b'', {'content-length': '20'}),
                     (206, b'x', {'content-range': 'bytes 0-0/20'})]
        with (patch.object(p.sys, 'platform', 'darwin'),
              patch.object(p, 'mac_transfer', side_effect=responses) as transfer):
            p.verify_enclosure('https://github.com/audio', 20)
        self.assertEqual(transfer.call_args_list[0].args[1], 'HEAD')
        self.assertEqual(transfer.call_args_list[1].kwargs['headers'], {'Range': 'bytes=0-0'})
        self.assertEqual(transfer.call_args_list[1].kwargs['max_size'], 1)
        self.assertNotIn('Authorization', transfer.call_args_list[1].kwargs['headers'])

    def test_invalid_native_range_response_rejected(self):
        responses = [(200, b'', {'content-length': '20'}), (200, b'xx', {})]
        with (patch.object(p.sys, 'platform', 'darwin'),
              patch.object(p, 'mac_transfer', side_effect=responses)):
            with self.assertRaises(p.Failure):
                p.verify_enclosure('https://github.com/audio', 20)


class SetupRetryTests(unittest.TestCase):
    def test_network_retry_keeps_token_and_does_not_reopen_github(self):
        responses = [('Paste Token', ''), ('Connect', 'github_pat_existing'), ('Try Again', '')]
        success = {'repo': 'owner/show', 'feed_url': 'https://owner.github.io/show/feed.xml'}
        with (patch.object(installer, 'dialog', side_effect=responses) as dialog,
              patch.object(installer.subprocess, 'run') as run,
              patch.object(installer.publisher, 'setup', side_effect=[p.NetworkFailure('network down'), success]) as setup):
            self.assertEqual(installer.connect('owner/show'), success)
        self.assertEqual(dialog.call_count, 3)
        self.assertEqual(setup.call_count, 2)
        self.assertEqual([call.args[1] for call in setup.call_args_list], ['github_pat_existing'] * 2)
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
