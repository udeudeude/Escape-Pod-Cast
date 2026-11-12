"""Regression checks for the two feed URLs and iPhone import routing."""
import pathlib
import unittest
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "docs/feed.xml"
COMPAT = next((ROOT / "docs/feeds").glob("*/feed.xml"), None)

class FeedCompatibilityTests(unittest.TestCase):
    def test_canonical_exists(self):
        self.assertTrue(CANONICAL.is_file())

    def test_compatibility_feed_exists(self):
        self.assertIsNotNone(COMPAT)

    def test_feeds_have_same_episode_identifiers(self):
        def guids(path):
            root = ET.parse(path).getroot()
            return [item.findtext("guid") for item in root.findall("./channel/item")]
        self.assertEqual(guids(CANONICAL), guids(COMPAT))

    def test_importers_write_both_feeds(self):
        for filename in ("import_audio_link_action.py", "import_youtube_action.py"):
            content = (ROOT / "scripts" / filename).read_text()
            self.assertIn('tree.write("docs/feed.xml"', content)

    def test_iphone_uses_original_feed(self):
        html = (ROOT / "docs/app/index.html").read_text()
        self.assertIn("state.path='docs/feed.xml'", html)
        self.assertIn("import-audio-link.yml", html)
        self.assertIn("import-youtube.yml", html)

if __name__ == "__main__":
    unittest.main()
