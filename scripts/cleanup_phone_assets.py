#!/usr/bin/env python3
"""Delete old phone-managed Release assets, never unrelated files."""
import datetime as dt
import json
import os
import subprocess
from urllib.parse import urlsplit

repo = os.environ["GITHUB_REPOSITORY"]
def gh(*args):
    return json.loads(subprocess.check_output(["gh", "api", *args], text=True))
assets = gh(f"repos/{repo}/releases/tags/audio").get("assets", [])
now = dt.datetime.now(dt.timezone.utc)
for asset in assets:
    name = asset.get("name", "")
    if not name.startswith("epc-phone-"):
        continue
    try:
        created = dt.datetime.fromisoformat(asset["created_at"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        continue
    if now - created < dt.timedelta(days=14):
        continue
    subprocess.run(["gh", "api", "-X", "DELETE", f"repos/{repo}/releases/assets/{asset['id']}"], check=True)
    print("Removed expired phone asset:", name)
