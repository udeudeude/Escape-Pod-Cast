#!/usr/bin/env python3
"""Discover direct audio links from one public webpage. No imports occur."""
import datetime as dt
import html.parser
import ipaddress
import json
import os
import pathlib
import socket
import urllib.parse
import urllib.request

URL = os.environ["PAGE_URL"].strip()
REQUEST_ID = os.environ["REQUEST_ID"].strip()
if not (len(REQUEST_ID) == 32 and all(c in "0123456789abcdef" for c in REQUEST_ID)):
    raise ValueError("Invalid request ID")

def check(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in (None, 443):
        raise ValueError("Only public HTTPS pages are supported")
    if p.hostname.lower() == "localhost" or p.hostname.lower().endswith((".local", ".internal")):
        raise ValueError("Local addresses are not supported")
    for entry in socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(entry[4][0]).is_global:
            raise ValueError("Non-public host is not supported")

class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

class Collector(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.current = None
        self.label = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self.current = attrs.get("href")
            self.label = []
        if tag in ("audio", "source") and attrs.get("src"):
            self.links.append((attrs["src"], attrs.get("title", "")))
    def handle_data(self, data):
        if self.current is not None:
            self.label.append(data)
    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.links.append((self.current, " ".join(self.label).strip()))
            self.current = None
            self.label = []

check(URL)
opener = urllib.request.build_opener(Redirects)
request = urllib.request.Request(URL, headers={"User-Agent": "EscapePodCast/1"})
with opener.open(request, timeout=25) as response:
    check(response.url)
    if "text/html" not in response.headers.get("Content-Type", "").lower():
        raise ValueError("URL is not an HTML page")
    if int(response.headers.get("Content-Length", "0") or "0") > 2_000_000:
        raise ValueError("Page is too large")
    content = response.read(2_000_001)
    if len(content) > 2_000_000:
        raise ValueError("Page is too large")
    final_url = response.url
parser = Collector()
parser.feed(content.decode("utf-8", errors="replace"))
found = []
seen = set()
for link, label in parser.links:
    candidate = urllib.parse.urljoin(final_url, link)
    parsed = urllib.parse.urlsplit(candidate)
    if parsed.scheme != "https" or pathlib.PurePosixPath(parsed.path).suffix.lower() not in (".mp3", ".m4a", ".aac", ".mp4", ".wav"):
        continue
    try:
        check(candidate)
    except (ValueError, OSError):
        continue
    if candidate in seen:
        continue
    seen.add(candidate)
    title = label.strip() or urllib.parse.unquote(pathlib.PurePosixPath(parsed.path).stem).replace("_", " ")
    found.append({"url": candidate, "title": title[:160]})
    if len(found) >= 100:
        break
output = pathlib.Path("docs/discovery") / (REQUEST_ID + ".json")
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps({"source": URL, "created_at": dt.datetime.now(dt.timezone.utc).isoformat(), "tracks": found}, ensure_ascii=False), encoding="utf-8")
print(f"Discovered {len(found)} direct audio links")
