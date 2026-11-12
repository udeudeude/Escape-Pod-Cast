#!/usr/bin/env python3
"""Publish a selected batch as one feed transaction, with idempotent retries."""
import datetime as dt
import json
import os
import pathlib
import subprocess
import uuid
import xml.etree.ElementTree as ET
from email.utils import format_datetime

from importlib.util import spec_from_file_location, module_from_spec

items=json.loads(os.environ["EPISODE_BATCH"])
if not isinstance(items,list) or not 1<=len(items)<=30:
    raise ValueError("Select 1 to 30 recordings")
request_id=os.environ["BATCH_ID"]
if len(request_id)!=32 or any(c not in "0123456789abcdef" for c in request_id):
    raise ValueError("Invalid batch identifier")
feed=pathlib.Path("docs/feed.xml")
compat=list(pathlib.Path("docs/feeds").glob("*/feed.xml"))
if len(compat)!=1: raise ValueError("Expected exactly one compatibility feed")
def validate(item):
    from urllib.parse import urlsplit
    u=urlsplit(item["url"])
    if u.scheme!="https" or not u.hostname or u.username or u.password:
        raise ValueError("Invalid audio URL")
    if pathlib.PurePosixPath(u.path).suffix.lower() not in (".mp3",".m4a",".aac",".wav",".mp4"):
        raise ValueError("Not a direct audio file")
    return u
for item in items: validate(item)
for attempt in range(6):
    subprocess.run(["git","fetch","origin","main"],check=True)
    subprocess.run(["git","reset","--hard","origin/main"],check=True)
    tree=ET.parse(feed)
    channel=tree.getroot().find("channel")
    if channel is None: raise ValueError("Invalid feed")
    existing={x.get("url") for x in channel.findall("item/enclosure")}
    added=0
    for item in items:
        url=item["url"]
        if url in existing: continue
        # Reuse the same validated remote metadata inspection as individual imports.
        import urllib.request
        req=urllib.request.Request(url,method="HEAD",headers={"User-Agent":"EscapePodCast/1"})
        with urllib.request.urlopen(req,timeout=35) as response:
            length=response.headers.get("Content-Length")
            if not length or not length.isdecimal() or not 0<int(length)<=2_000_000_000:
                raise ValueError("Audio file size unavailable: "+url)
        extension=pathlib.PurePosixPath(validate(item).path).suffix.lower()
        mime={".mp3":"audio/mpeg",".m4a":"audio/mp4",".mp4":"audio/mp4",".aac":"audio/aac",".wav":"audio/wav"}[extension]
        element=ET.Element("item")
        title=(item.get("title") or pathlib.PurePosixPath(validate(item).path).stem)[:180]
        ET.SubElement(element,"title").text=title
        ET.SubElement(element,"description").text=title
        ET.SubElement(element,"guid",{"isPermaLink":"false"}).text="epc-batch-"+uuid.uuid5(uuid.NAMESPACE_URL,url).hex
        ET.SubElement(element,"pubDate").text=format_datetime(dt.datetime.now(dt.timezone.utc),usegmt=True)
        ET.SubElement(element,"enclosure",{"url":url,"length":length,"type":mime})
        first=channel.find("item")
        channel.insert(list(channel).index(first) if first is not None else len(channel),element)
        existing.add(url)
        added+=1
    tree.write(feed,encoding="utf-8",xml_declaration=True)
    compat[0].write_bytes(feed.read_bytes())
    output=pathlib.Path("docs/batches")/(request_id+".json")
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({"request_id":request_id,"status":"complete","requested":len(items),"added":added,"already_present":len(items)-added}))
    subprocess.run(["git","add","docs/feed.xml",str(compat[0]),str(output)],check=True)
    subprocess.run(["git","commit","-m","Publish selected audio batch"],check=True)
    if subprocess.run(["git","push","origin","HEAD:main"]).returncode==0:
        print("Batch committed:",added,"new episodes")
        break
else:
    raise SystemExit("Concurrent feed updates prevented publication after six retries")
