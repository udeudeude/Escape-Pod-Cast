import datetime as dt
import pathlib
import tempfile
import unittest
import xml.etree.ElementTree as ET
from scripts.expire_web_episodes import expire

class ExpirationTests(unittest.TestCase):
    def test_expires_only_old_web_items(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "feed.xml"
            path.write_text("""<rss><channel>
            <item><guid>epc-link-old</guid><pubDate>Thu, 01 Oct 2026 12:00:00 GMT</pubDate></item>
            <item><guid>epc-link-new</guid><pubDate>Thu, 12 Nov 2026 12:00:00 GMT</pubDate></item>
            <item><guid>mac-legacy</guid><pubDate>Thu, 01 Oct 2026 12:00:00 GMT</pubDate></item>
            </channel></rss>""")
            count = expire(path, dt.datetime(2026, 11, 13, tzinfo=dt.timezone.utc))
            self.assertEqual(count, 1)
            ids = [x.text for x in ET.parse(path).getroot().findall("./channel/item/guid")]
            self.assertEqual(ids, ["epc-link-new", "mac-legacy"])
if __name__ == "__main__":
    unittest.main()
