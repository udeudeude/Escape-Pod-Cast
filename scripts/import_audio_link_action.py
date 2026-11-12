#!/usr/bin/env python3
"""Inspect a public direct audio URL and publish its enclosure to the existing feed."""
import datetime as dt
import ipaddress
import os
import pathlib
import socket
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

url = os.environ["EPISODE_URL"].strip()
title = os.environ.get("EPISODE_TITLE", "").strip()
description = os.environ.get("EPISODE_DESCRIPTION", "").strip()
allowed = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".mp4": "audio/mp4", ".wav": "audio/wav"}

def validate(address):
    parsed = urllib.parse.urlsplit(address)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Only public HTTPS audio addresses are supported")
    if parsed.hostname.lower() in ("localhost",) or parsed.hostname.lower().endswith((".local", ".internal")):
        raise ValueError("Local host forbidden")
    for result in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM):
        ip = ipaddress.ip_address(result[4][0])
        if not ip.is_global:
            raise ValueError("Audio host resolves to a non-public address")
    return parsed

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

parsed = validate(url)
extension = pathlib.PurePosixPath(parsed.path).suffix.lower()
if extension not in allowed:
    raise ValueError("Use a direct MP3, M4A, AAC, MP4 or WAV URL")
opener = urllib.request.build_opener(SafeRedirect)
request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "EscapePodCast/1"})
with opener.open(request, timeout=35) as response:
    length = response.headers.get("Content-Length")
    content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
    final_url = response.url
    validate(final_url)
if not length or not length.isdecimal() or int(length) < 1:
    raise ValueError("Server did not report a usable Content-Length")
if int(length) > 2_000_000_000:
    raise ValueError("File exceeds 2 GB limit")
if content_type and content_type not in (allowed[extension], "application/octet-stream", "binary/octet-stream", "audio/x-wav", "audio/mp3", "audio/x-m4a"):
    raise ValueError(f"Server returned unexpected content type: {content_type}")
with opener.open(urllib.request.Request(url, headers={"Range": "bytes=0-0", "User-Agent": "EscapePodCast/1"}), timeout=35) as response:
    if response.status not in (200, 206):
        raise ValueError("Audio byte request failed")
feed_paths = list(pathlib.Path("docs/feeds").glob("*/feed.xml"))
if len(feed_paths) != 1:
    raise ValueError(f"Expected one existing feed, found {len(feed_paths)}")
feed = feed_paths[0]
tree = ET.parse(feed)
channel = tree.getroot().find("channel")
if channel is None:
    raise ValueError("Invalid feed: no channel")
title = (title or urllib.parse.unquote(pathlib.PurePosixPath(parsed.path).stem).replace("_", " ").replace("-", " ") or "Audio episode")[:180]
item = ET.Element("item")
ET.SubElement(item, "title").text = title
ET.SubElement(item, "description").text = description or title
ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = "epc-link-" + uuid.uuid4().hex
ET.SubElement(item, "pubDate").text = dt.datetime.now(dt.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
ET.SubElement(item, "enclosure", {"url": final_url, "length": length, "type": allowed[extension]})
first = channel.find("item")
channel.insert(list(channel).index(first) if first is not None else len(channel), item)
tree.write(feed, encoding="utf-8", xml_declaration=True)
print(f"Published {title} ({length} bytes)")
