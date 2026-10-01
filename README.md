# Escape Pod Cast

Drop audio files into a password-protected web page and publish each one as an episode in a private-by-secret-link podcast feed.

## Features

- multiple-file drag and drop
- MP3, M4A, AAC, WAV, FLAC, OGG, OPUS, and audio MP4
- editable title and notes before publishing
- browser-derived duration metadata when available
- RSS 2.0 feed with podcast tags
- byte-range audio serving for podcast seeking/downloads
- password-protected uploader
- unguessable feed/media token for podcast clients
- persistent on-disk library and episode deletion
- no third-party runtime packages; Node 20+ only

## Render deployment

This repository includes `render.yaml`. In Render, create a Blueprint from this repository and supply `ADMIN_PASSWORD` when prompted. Render generates the private feed token automatically.

The persistent disk is the podcast library. Without persistent storage, uploaded episodes can disappear on redeploy/replacement.

## Privacy model

The uploader uses browser Basic authentication. The podcast itself uses a long secret URL rather than an interactive login, because podcast clients vary in authenticated-feed support. Treat the subscription URL as a password: anyone who gets it can retrieve the feed and audio.
