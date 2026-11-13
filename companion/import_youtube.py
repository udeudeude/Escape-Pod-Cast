#!/usr/bin/env python3
"""Optional personal-device YouTube import companion.

Run on a computer you control, not on GitHub's shared runners.
Uses yt-dlp installed locally, then sends the resulting audio to the existing
Escape Pod Cast upload service. No YouTube cookies are collected or transmitted.
"""
import argparse
import getpass
import json
import mimetypes
import os
import pathlib
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

UPLOAD = "https://escape-pod-upload.onrender.com/upload"
def video_url(value):
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in {"youtube.com","www.youtube.com","m.youtube.com","youtu.be"}:
        raise ValueError("Expected a YouTube HTTPS URL")
    ident = parsed.path.strip("/") if parsed.hostname == "youtu.be" else urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
    if len(ident) != 11 or not all(c.isalnum() or c in "-_" for c in ident):
        raise ValueError("Invalid YouTube video ID")
    return "https://www.youtube.com/watch?v=" + ident

def main():
    parser = argparse.ArgumentParser(description="Import one YouTube recording from your own computer")
    parser.add_argument("url", help="YouTube video link")
    parser.add_argument("--title", default="", help="Optional episode title")
    parser.add_argument("--notes", default="", help="Optional episode description")
    parser.add_argument("--token-env", default="ESCAPE_POD_GITHUB_TOKEN", help="Environment variable containing GitHub token")
    args = parser.parse_args()
    url = video_url(args.url)
    token = os.environ.get(args.token_env) or getpass.getpass("GitHub fine-grained token (not saved): ")
    if not token.startswith("github_pat_"):
        raise SystemExit("Expected a fine-grained GitHub token")
    with tempfile.TemporaryDirectory(prefix="escape-pod-") as folder:
        target = str(pathlib.Path(folder) / "recording.%(ext)s")
        command = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-config", "--max-filesize", "100M",
                   "--extract-audio", "--audio-format", "mp3", "--audio-quality", "5",
                   "--output", target, "--print", "after_move:title", url]
        print("Downloading on your personal device...")
        proc = subprocess.run(command, capture_output=True, text=True, timeout=1200)
        if proc.returncode:
            print(proc.stderr[-2000:], file=sys.stderr)
            raise SystemExit("Download failed. No podcast changes were made.")
        files = list(pathlib.Path(folder).glob("recording.*"))
        if len(files) != 1:
            raise SystemExit("Could not identify the converted audio file")
        file = files[0]
        if file.stat().st_size > 100 * 1024 * 1024:
            raise SystemExit("Audio exceeds upload limit")
        title = args.title or (proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "YouTube recording")
        print("Uploading", title)
        request = urllib.request.Request(UPLOAD, method="POST", data=file.read_bytes(), headers={
            "Authorization": "Bearer " + token,
            "Origin": "https://udeudeude.github.io",
            "Content-Type": "application/octet-stream",
            "X-Filename": urllib.parse.quote("recording.mp3", safe=""),
            "X-Title": urllib.parse.quote(title, safe=""),
            "X-Description": urllib.parse.quote(args.notes, safe=""),
        })
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            raise SystemExit("Upload failed: " + error.read(500).decode("utf-8", "replace"))
        print("Published:", payload.get("title", title))
        print("Podcast: https://udeudeude.github.io/Escape-Pod-Cast/feed.xml")

if __name__ == "__main__":
    main()
