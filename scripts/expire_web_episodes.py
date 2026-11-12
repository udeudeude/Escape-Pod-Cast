#!/usr/bin/env python3
"""Expire web-imported podcast items after 14 days; preserve legacy Mac entries."""
import datetime as dt
import pathlib
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
FEED = ROOT / "docs/feed.xml"
PREFIXES = ("epc-link-", "epc-web-")
DAYS = 14

def expire(path=FEED, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    tree = ET.parse(path)
    channel = tree.getroot().find("channel")
    removed = 0
    for item in list(channel.findall("item")):
        guid = item.findtext("guid", "")
        if not guid.startswith(PREFIXES):
            continue
        published = item.findtext("pubDate")
        try:
            from email.utils import parsedate_to_datetime
            date = parsedate_to_datetime(published).astimezone(dt.timezone.utc)
        except (TypeError, ValueError, IndexError):
            continue
        if now - date >= dt.timedelta(days=DAYS):
            channel.remove(item)
            removed += 1
    if removed:
        tree.write(path, encoding="utf-8", xml_declaration=True)
    return removed

def now_utc():
    return dt.datetime.now(dt.timezone.utc)

def main():
    removed = expire()
    compatibility = list((ROOT / "docs/feeds").glob("*/feed.xml"))
    if len(compatibility) != 1:
        raise SystemExit("Expected exactly one compatibility feed")
    if removed:
        compatibility[0].write_bytes(FEED.read_bytes())
    deleted = 0
    for file in (ROOT / "docs/discovery").glob("*.json") if (ROOT / "docs/discovery").exists() else []:
        import json
        try:
            record = json.loads(file.read_text(encoding="utf-8"))
            created = dt.datetime.fromisoformat(record["created_at"]).astimezone(dt.timezone.utc)
        except (KeyError, ValueError, TypeError, OSError):
            continue
        if now_utc() - created > dt.timedelta(days=2):
            file.unlink()
            deleted += 1
    print(f"Expired {removed} web episodes; removed {deleted} discovery results")
if __name__ == "__main__":
    main()
