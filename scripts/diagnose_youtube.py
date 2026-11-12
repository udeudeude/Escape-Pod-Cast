#!/usr/bin/env python3
"""Metadata-only YouTube diagnostics. No cookies or downloads."""
import json
import os
import pathlib
import subprocess
import sys
import urllib.parse

raw=os.environ["VIDEO_URL"]
u=urllib.parse.urlsplit(raw)
if u.scheme!="https" or u.hostname not in ("youtube.com","www.youtube.com","m.youtube.com","youtu.be"):
    raise SystemExit("Use a public YouTube URL")
if u.hostname=="youtu.be":
    video=u.path.strip("/")
else:
    video=urllib.parse.parse_qs(u.query).get("v",[""])[0]
if len(video)!=11 or not all(c.isalnum() or c in "_-" for c in video):
    raise SystemExit("Invalid YouTube video identifier")
url="https://www.youtube.com/watch?v="+video
cmd=[sys.executable,"-m","yt_dlp","--no-config","--skip-download","--dump-single-json","--no-playlist","--socket-timeout","20","--extractor-args","youtube:player-client=mweb,tv,web_safari",url]
try:
    result=subprocess.run(cmd,capture_output=True,text=True,timeout=120)
except subprocess.TimeoutExpired:
    raise SystemExit("YouTube metadata probe timed out")
if result.returncode:
    message=result.stderr[-4000:]
    if "Sign in to confirm" in message or "LOGIN_REQUIRED" in message:
        print("DIAGNOSIS: YouTube requires authentication or rejects this runner's network identity. A playback token alone is not a demonstrated solution.")
    elif "403" in message or "PO Token" in message:
        print("DIAGNOSIS: Format access or token requirements may be involved.")
    else:
        print("DIAGNOSIS: Extraction failed for another reason.")
    print(message)
    raise SystemExit(1)
try:
    data=json.loads(result.stdout)
except json.JSONDecodeError:
    raise SystemExit("Extractor did not return valid metadata")
print("METADATA SUCCESS:",data.get("title","Untitled"))
print("Available audio formats:",sum(1 for f in data.get("formats",[]) if f.get("acodec") not in ("none",None)))
print("This does not prove that audio downloading or publishing will succeed.")
