# Personal-device YouTube import (experimental)

YouTube blocks downloads from GitHub-hosted runners. This companion runs the extraction on a computer under your control, then uses the same upload service already proven by iPhone uploads. It does not ask for YouTube cookies or send YouTube account credentials to GitHub.

## Linux or Mac setup

Install Python 3.11 or newer, FFmpeg and yt-dlp:

```sh
python3 -m pip install -U yt-dlp
```

Install FFmpeg with your operating system's package manager. Then run:

```sh
python3 companion/import_youtube.py 'https://www.youtube.com/watch?v=VIDEO_ID'
```

Enter the existing fine-grained GitHub token when prompted. The script does not save it. Alternatively, set `ESCAPE_POD_GITHUB_TOKEN` in your shell.

The helper extracts a single public video's audio to MP3, enforces the 100 MB upload limit, publishes to the original podcast feed and deletes its temporary local file.

**Limitations:** This is an optional companion, not a fully iPhone-only solution. The personal computer must be running when used. It may still encounter YouTube restrictions. It does not install a background service, and it has not yet been verified end to end. Do not expose the helper as an unauthenticated public server.
