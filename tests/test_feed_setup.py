"""Feed migration is atomic, stable on retry, and independent across forks."""
import base64
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).parents[1] / 'mac'))
import escape_pod_cast as publisher
import install as installer


def file_item(content):
    return {'sha': 'file-sha', 'content': base64.b64encode(content.encode()).decode()}


def episode_feed(repo):
    root = publisher.new_feed()
    publisher.add_episode(root, {
        'id': 7, 'size': 123, 'content_type': 'audio/mpeg',
        'browser_download_url': 'https://github.com/' + repo + '/releases/download/audio/epc-file.mp3',
    }, 'Existing episode', publisher.dt.datetime.now(publisher.dt.timezone.utc))
    return ET.tostring(root, encoding='unicode')


class Repository(publisher.GitHub):
    def __init__(self, repo, files=None):
        super().__init__(repo, 'fake-token')
        self.files = {path: file_item(content) for path, content in (files or {}).items()}
        self.calls = []
        self.entries = []
        self.reject_move = False
        self.version = 'parent'

    def request(self, method, path, body=None, missing=False):
        self.calls.append((method, path, copy.deepcopy(body)))
        if method == 'GET' and path.startswith('/contents/'):
            name = path[len('/contents/'):].split('?')[0]
            if name in self.files:
                return copy.deepcopy(self.files[name])
            if missing:
                return None
            raise publisher.Failure('File missing: ' + name)
        if (method, path) == ('GET', '/git/ref/heads/main'):
            return {'object': {'sha': self.version}}
        if method == 'GET' and path.startswith('/git/commits/'):
            return {'tree': {'sha': 'base-tree'}}
        if (method, path) == ('POST', '/git/trees'):
            self.entries = body['tree']
            return {'sha': 'new-tree'}
        if (method, path) == ('POST', '/git/commits'):
            return {'sha': 'new-commit'}
        if (method, path) == ('PATCH', '/git/refs/heads/main'):
            if self.reject_move:
                raise publisher.Failure('Concurrent update')
            for entry in self.entries:
                if entry.get('sha', 'present') is None:
                    del self.files[entry['path']]
                else:
                    self.files[entry['path']] = file_item(entry['content'])
            self.version = body['sha']
            return None
        if method == 'PUT' and path.startswith('/contents/'):
            name = path[len('/contents/'):]
            if body['sha'] != self.files[name]['sha']:
                raise publisher.Failure('Incorrect feed SHA')
            self.files[name] = {'sha': 'updated-sha', 'content': body['content']}
            return None
        raise AssertionError((method, path, body))


class FeedMigrationTests(unittest.TestCase):
    def test_existing_feed_moves_atomically_without_changing_episode(self):
        original = episode_feed('owner/show')
        client = Repository('owner/show', {publisher.LEGACY_FEED: original})
        path = client.initialize_feed()
        self.assertRegex(path, publisher.FEED_PATH)
        self.assertEqual(len(path.split('/')[2]), 48)
        self.assertNotIn(publisher.LEGACY_FEED, client.files)
        root, sha = client.read_feed()
        expected = publisher.channel(ET.fromstring(original)).find('item')
        self.assertEqual(ET.tostring(publisher.channel(root).find('item')), ET.tostring(expected))
        self.assertEqual(publisher.channel(root).findtext('link'), 'https://github.com/owner/show')
        self.assertNotIn(path[len('docs/'):], base64.b64decode(client.files['docs/index.html']['content']).decode())
        moves = [body for method, route, body in client.calls if method == 'PATCH']
        self.assertEqual(moves, [{'sha': 'new-commit', 'force': False}])
        settings = json.loads(base64.b64decode(client.files[publisher.FEED_SETTINGS]['content']))
        self.assertEqual(settings['repo'], 'owner/show')
        self.assertEqual(settings['feed_path'], path)

    def test_reinstall_keeps_the_same_address_and_writes_to_it(self):
        client = Repository('owner/show', {publisher.LEGACY_FEED: episode_feed('owner/show')})
        first = client.initialize_feed()
        again = Repository('owner/show')
        again.files = client.files
        self.assertEqual(again.initialize_feed(), first)
        self.assertFalse(any(method == 'POST' for method, _, _ in again.calls))
        root, sha = again.read_feed()
        again.write_feed(root, sha)
        self.assertEqual(again.calls[-1][1], '/contents/' + first)

    def test_concurrent_publish_keeps_the_old_feed_and_settings_unchanged(self):
        client = Repository('owner/show', {publisher.LEGACY_FEED: episode_feed('owner/show')})
        original = copy.deepcopy(client.files)
        client.reject_move = True
        with self.assertRaises(publisher.Failure):
            client.initialize_feed()
        self.assertEqual(client.files, original)
        self.assertIsNone(client.feed_path)
        client.reject_move = False
        self.assertRegex(client.initialize_feed(), publisher.FEED_PATH)

    def test_new_repository_can_start_without_a_feed(self):
        client = Repository('owner/show')
        self.assertRegex(client.initialize_feed(), publisher.FEED_PATH)
        self.assertEqual(publisher.channel(client.read_feed()[0]).findall('item'), [])

    def test_lost_network_response_reuses_already_migrated_feed(self):
        client = Repository('owner/show', {publisher.LEGACY_FEED: episode_feed('owner/show')})
        request = client.request

        def lose_response(method, path, body=None, missing=False):
            result = request(method, path, body, missing)
            if method == 'PATCH':
                raise publisher.NetworkFailure('Response lost after successful update')
            return result

        with patch.object(client, 'request', side_effect=lose_response):
            with self.assertRaises(publisher.NetworkFailure):
                client.initialize_feed()
        settings = json.loads(base64.b64decode(client.files[publisher.FEED_SETTINGS]['content']))
        self.assertEqual(client.initialize_feed(), settings['feed_path'])
        self.assertEqual(len(publisher.channel(client.read_feed()[0]).findall('item')), 1)

    def test_fork_gets_new_address_and_drops_copied_parent_episodes(self):
        parent_path = 'docs/feeds/' + 'a' * 48 + '/feed.xml'
        settings = json.dumps({'version': 1, 'repo': 'parent/show', 'feed_path': parent_path})
        client = Repository('newowner/show', {
            publisher.FEED_SETTINGS: settings, parent_path: episode_feed('parent/show')})
        with patch.object(publisher.secrets, 'token_hex', return_value='b' * 48) as random:
            path = client.initialize_feed()
        random.assert_called_once_with(24)
        self.assertNotEqual(path, parent_path)
        self.assertNotIn(parent_path, client.files)
        root, _ = client.read_feed()
        self.assertEqual(publisher.channel(root).findall('item'), [])
        self.assertEqual(publisher.channel(root).findtext('link'), 'https://github.com/newowner/show')

    def test_legacy_fork_does_not_copy_parent_episodes(self):
        client = Repository('newowner/show', {publisher.LEGACY_FEED: episode_feed('parent/show')})
        client.initialize_feed()
        self.assertEqual(publisher.channel(client.read_feed()[0]).findall('item'), [])

    def test_invalid_own_settings_fail_without_mutating_repository(self):
        client = Repository('owner/show', {publisher.FEED_SETTINGS: json.dumps({
            'version': 1, 'repo': 'owner/show', 'feed_path': '../other/file'})})
        with self.assertRaises(publisher.Failure):
            client.initialize_feed()
        self.assertFalse(any(method != 'GET' for method, _, _ in client.calls))

    def test_publisher_discovers_existing_random_path_without_setup(self):
        path = 'docs/feeds/' + 'c' * 48 + '/feed.xml'
        client = Repository('owner/show', {
            publisher.FEED_SETTINGS: json.dumps({'version': 1, 'repo': 'owner/show', 'feed_path': path}),
            path: episode_feed('owner/show')})
        root, _ = client.read_feed()
        self.assertEqual(client.feed_path, path)
        self.assertEqual(len(publisher.channel(root).findall('item')), 1)


class IndependentSetupTests(unittest.TestCase):
    def test_new_user_is_guided_to_their_own_copy_with_no_author_default(self):
        answers = [('Create My Copy', ''), ('Continue', 'someone/their-show')]
        with patch.object(installer, 'dialog', side_effect=answers) as dialog, \
                patch.object(installer.subprocess, 'run') as run:
            self.assertEqual(installer.choose_repository(), 'someone/their-show')
        self.assertEqual(run.call_args.args[0], [
            '/usr/bin/open', 'https://github.com/udeudeude/Escape-Pod-Cast/fork'])
        self.assertEqual(dialog.call_args.kwargs['text'], '')
        self.assertNotIn('udeudeude', dialog.call_args.args[0])

    def test_existing_user_updates_their_own_repository(self):
        with patch.object(installer, 'dialog', return_value=('Update', '')), \
                patch.object(installer.subprocess, 'run') as run:
            self.assertEqual(installer.choose_repository({'repo': 'owner/show'}), 'owner/show')
        run.assert_not_called()

    def test_saved_token_is_reused_during_feed_migration(self):
        config = {'repo': 'owner/show', 'feed_url': 'https://example.com/random/feed.xml'}
        with patch.object(installer.publisher, 'setup', return_value=config) as setup, \
                patch.object(installer, 'dialog', side_effect=AssertionError('unexpected prompt')), \
                patch.object(installer.subprocess, 'run') as run:
            self.assertEqual(installer.connect('owner/show', 'existing_token'), config)
        setup.assert_called_once_with('owner/show', 'existing_token', progress=installer.notify)
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
