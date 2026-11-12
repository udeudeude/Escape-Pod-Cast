#!/usr/bin/env python3
"""Publish one authorized YouTube audio item into the existing Escape Pod Cast feed."""
import datetime as dt
import glob
import os
import pathlib
import subprocess
import sys
import tempfile
import urllib.request
import uuid
import xml.etree.ElementTree as ET

URL = os.environ["EPISODE_URL"]
if not URL.startswith(("https://www.youtube.com/watch?", "https://youtu.be/", "https://m.youtube.com/watch?", "https://www.youtube.com/shorts/")):
    raise SystemExit("Only supported YouTube video URLs are accepted")
if len(URL) > 2048:
    raise SystemExit("URL too long")
feeds = glob.glob("docs/feeds/*/feed.xml")
if len(feeds) != 1:
    raise SystemExit(f"Expected one existing feed, found {len(feeds)}")
feed = pathlib.Path(feeds[0])
repo = os.environ["GITHUB_REPOSITORY"]
with tempfile.TemporaryDirectory() as directory:
    target = os.path.join(directory, "audio.%(ext)s")
    command = [
        sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-config",
        "--no-warnings", "--max-filesize", "250M", "--socket-timeout", "30",
        "--retries", "2", "--extract-audio", "--audio-format", "mp3",
        "--audio-quality", "5", "--output", target,
        "--print", "after_move:title", URL
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=900, check=True)
    files = list(pathlib.Path(directory).glob("audio.*"))
    if len(files) != 1 or files[0].suffix.lower() != ".mp3":
        raise SystemExit("No MP3 output produced")
    audio = files[0]
    if audio.stat().st_size > 250_000_000:
        raise SystemExit("Audio exceeds 250 MB limit")
    title = os.environ.get("EPISODE_TITLE", "").strip() or (result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "YouTube audio")
    title = title[:180]
    asset_name = "epc-web-" + uuid.uuid4().hex + ".mp3"
    staged = pathlib.Path(directory) / asset_name
    audio.rename(staged)
    release = subprocess.run(["gh", "release", "view", "audio"], capture_output=True)
    if release.returncode:
        subprocess.run(["gh", "release", "create", "audio", "--title", "Temporary podcast audio", "--notes", "Managed Escape Pod Cast audio"], check=True)
    subprocess.run(["gh", "release", "upload", "audio", str(staged), "--clobber"], check=True)
    enclosure_url = f"https://github.com/{repo}/releases/download/audio/{asset_name}"
    request = urllib.request.Request(enclosure_url, headers={"Range": "bytes=0-0", "User-Agent": "EscapePodCast/1"})
    with urllib.request.urlopen(request, timeout=45) as response:
        if response.status not in (200, 206):
            raise SystemExit("Uploaded audio not publicly available")
    tree = ET.parse(feed)
    root = tree.getroot()
    channel = root.find("channel")
    if channel is None:
        raise SystemExit("Missing channel")
    item = ET.Element("item")
    ET.SubElement(item, "title").text = title
    ET.SubElement(item, "description").text = title
    ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = "epc-web-" + uuid.uuid4().hex
    ET.SubElement(item, "pubDate").text = dt.datetime.now(dt.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    ET.SubElement(item, "enclosure", {"url": enclosure_url, "length": str(staged.stat().st_size), "type": "audio/mpeg"})
    first = channel.find("item")
    if first is None:
        channel.append(item)
    else:
        channel.insert(list(channel).index(first), item)
    tree.write(feed, encoding="utf-8", xml_declaration=True)
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=True)
    subprocess.run(["git", "add", str(feed)], check=True)
    subprocess.run(["git", "commit", "-m", "Publish imported YouTube audio"], check=True)
    subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=True)
    subprocess.run(["git", "push", "origin", "HEAD:main"], check=True)
