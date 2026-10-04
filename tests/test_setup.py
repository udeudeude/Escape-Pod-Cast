"""Setup boundary checks: no credentials in process arguments, recoverable API writes."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.parse

MAC = Path(__file__).parents[1] / 'mac'
sys.path.insert(0, str(MAC))
import escape_pod_cast as publisher

SPEC = importlib.util.spec_from_file_location('installer', MAC / 'install.py')
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class DialogTests(unittest.TestCase):
    def test_secret_is_received_via_dialog_without_argv_or_default_value(self):
        completed = subprocess.CompletedProcess([], 0, 'Connect\ngithub_pat_fake\n', '')
        with patch.object(installer.subprocess, 'run', return_value=completed) as run:
            result = installer.dialog('Paste token', buttons=('Cancel', 'Connect'), text='', hidden=True)
        self.assertEqual(result, ('Connect', 'github_pat_fake'))
        self.assertEqual(run.call_args.args[0], ['/usr/bin/osascript', '-'])
        self.assertIn('with hidden answer', run.call_args.kwargs['input'])
        self.assertNotIn('github_pat_fake', run.call_args.kwargs['input'])

    def test_cancel_is_not_reported_as_failure(self):
        completed = subprocess.CompletedProcess([], 1, '', 'User canceled. (-128)')
        with patch.object(installer.subprocess, 'run', return_value=completed):
            with self.assertRaises(installer.Cancelled):
                installer.dialog('Welcome')

    def test_token_template_prefills_only_needed_permissions(self):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(installer.token_url('owner/my-show')).query)
        self.assertEqual(query['target_name'], ['owner'])
        self.assertEqual(query['contents'], ['write'])
        self.assertEqual(query['pages'], ['write'])
        self.assertEqual(query['administration'], ['write'])
        self.assertNotIn('workflows', query)

    def test_droplet_has_picker_and_escapes_paths(self):
        source = installer.droplet_source('/a "quoted"/python3', '/path/publisher.py',
                                          '/path/drop', '/path/log', 'https://example.com/feed.xml')
        self.assertIn('choose file', source)
        self.assertIn('with multiple selections allowed', source)
        self.assertIn('Copy podcast link', source)
        self.assertIn('quoted form of', source)
        self.assertIn('/a \\"quoted\\"/python3', source)


class SetupTests(unittest.TestCase):
    def test_pages_update_204_is_followed_by_read_and_secret_uses_stdin(self):
        calls = []
        pages = {'html_url': 'https://owner.github.io/show/',
                 'source': {'branch': 'main', 'path': '/docs'}, 'build_type': 'legacy'}
        get_count = 0

        class Client:
            def __init__(self, repo, token):
                pass

            def read_feed(self):
                return None

            def request(self, method, path, body=None, missing=False):
                nonlocal get_count
                calls.append((method, path))
                if path == '':
                    return {'private': False, 'default_branch': 'main'}
                if path == '/releases/tags/audio':
                    return {'id': 1}
                if method == 'GET' and path == '/pages':
                    get_count += 1
                    return {'source': {'path': '/'}, 'build_type': 'workflow'} if get_count == 1 else pages
                if method == 'PUT' and path == '/pages':
                    return None  # GitHub returns 204, not a JSON Pages object.
                raise AssertionError((method, path))

        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            result = subprocess.CompletedProcess([], 0, '', '')
            with (patch.object(publisher, 'GitHub', Client),
                  patch.object(publisher, 'HOME', home),
                  patch.object(publisher, 'CONFIG', home / 'config.json'),
                  patch.object(publisher, 'get_token', return_value='github_pat_fake'),
                  patch.object(publisher.subprocess, 'run', return_value=result) as run,
                  patch.object(publisher.getpass, 'getpass', side_effect=AssertionError('terminal prompt'))):
                config = publisher.setup('owner/show', 'github_pat_fake', progress=lambda _: None)
            self.assertEqual(config['feed_url'], 'https://owner.github.io/show/feed.xml')
            self.assertEqual(json.loads((home / 'config.json').read_text()), config)
            self.assertNotIn('github_pat_fake', (home / 'config.json').read_text())
            self.assertEqual(calls[-2:], [('PUT', '/pages'), ('GET', '/pages')])
            self.assertEqual(run.call_args.args[0], ['/usr/bin/security', '-i'])
            self.assertIn('github_pat_fake', run.call_args.kwargs['input'])

    def test_bad_token_rejected_before_network(self):
        with patch.object(publisher, 'GitHub') as client:
            with self.assertRaises(publisher.Failure):
                publisher.setup('owner/show', 'token with spaces')
        client.assert_not_called()


if __name__ == '__main__':
    unittest.main()
