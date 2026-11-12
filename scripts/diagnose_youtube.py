#!/usr/bin/env python3
"""Public metadata-only YouTube probe, with a durable per-request result."""
import json
import os
import pathlib
import subprocess
import sys
import urllib.parse

raw=os.environ["VIDEO_URL"]
request_id=os.environ["REQUEST_ID"]
if len(request_id)!=32 or any(c not in "0123456789abcdef" for c in request_id):
    raise SystemExit("Invalid request identifier")
result_path=pathlib.Path("docs/diagnostics")/(request_id+".json")
result_path.parent.mkdir(parents=True,exist_ok=True)
result={"request_id":request_id,"status":"failed","category":"unknown","message":"Diagnostic did not complete"}
try:
    u=urllib.parse.urlsplit(raw)
    if u.scheme!="https" or u.hostname not in ("youtube.com","www.youtube.com","m.youtube.com","youtu.be"):
        raise ValueError("Use a public YouTube URL")
    video=u.path.strip("/") if u.hostname=="youtu.be" else urllib.parse.parse_qs(u.query).get("v",[""])[0]
    if len(video)!=11 or not all(c.isalnum() or c in "_-" for c in video):
        raise ValueError("Invalid YouTube video identifier")
    url="https://www.youtube.com/watch?v="+video
    cmd=[sys.executable,"-m","yt_dlp","--no-config","--skip-download","--dump-single-json","--no-playlist","--socket-timeout","20","--extractor-args","youtube:player-client=mweb,tv,web_safari",url]
    probe=subprocess.run(cmd,capture_output=True,text=True,timeout=120)
    if probe.returncode:
        details=probe.stderr[-1500:]
        if "Sign in to confirm" in details or "LOGIN_REQUIRED" in details:
            category="sign_in_required"
            message="YouTube rejected this server's request and requires sign-in. Audio was not downloaded."
        elif "403" in details or "PO Token" in details:
            category="format_restricted"
            message="YouTube restricted format access. Playback-token support may be required."
        else:
            category="extractor_error"
            message="YouTube metadata extraction failed."
        result.update(category=category,message=message,details=details)
    else:
        data=json.loads(probe.stdout)
        audio=sum(1 for fmt in data.get("formats",[]) if fmt.get("acodec") not in ("none",None))
        result.update(status="success",category="metadata_available",title=data.get("title","Untitled"),audio_formats=audio,message="Metadata is available. Audio downloading and publishing have not been verified.")
except (ValueError,subprocess.TimeoutExpired,json.JSONDecodeError) as exc:
    result.update(category="probe_error",message=str(exc)[:400])
finally:
    result_path.write_text(json.dumps(result,ensure_ascii=False),encoding="utf-8")
    print("YouTube diagnosis:",result["category"],result["message"])
