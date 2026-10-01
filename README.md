# Escape Pod Cast

**Drop an audio file in a web page. It appears as a new episode in your own personal podcast.**

Escape Pod Cast is an open-source machine for turning arbitrary audio into a private-by-secret-link podcast feed. Each person deploys their own copy, connects their own object-storage bucket, and gets their own feed.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/udeudeude/Escape-Pod-Cast)

## The $0 default

The guided setup uses:

- **Render free web service** for the small application server.
- **Backblaze B2** for a private audio library. Backblaze currently offers the first 10 GB free and says no credit card is required to start.
- No Render disk and no public storage bucket.

See **[SETUP.md](SETUP.md)** for the click-by-click setup.

## What it does

1. Sign into your password-protected uploader.
2. Drop one or several audio files.
3. Optionally edit titles and notes.
4. Tap **Publish**.
5. Audio streams directly into your private S3-compatible bucket.
6. Episode metadata is stored in that same bucket.
7. Your RSS feed immediately includes the new episode.
8. Podcast clients retrieve audio through Escape Pod Cast, which supports byte-range requests for seeking and downloads.

The Render service stores nothing important locally, so it can restart or redeploy without losing your library.

## Bring your own storage

The application is provider-neutral. It accepts:

- `STORAGE_ENDPOINT`
- `STORAGE_REGION`
- `STORAGE_ACCESS_KEY_ID`
- `STORAGE_SECRET_ACCESS_KEY`
- `STORAGE_BUCKET`

Backblaze B2 is the default because it supports the S3-compatible API and can be started without a payment method. Cloudflare R2 and other S3-compatible services can be substituted.

## Privacy

- The uploader is password-protected.
- Each installation gets a long random `FEED_TOKEN`.
- The storage bucket can remain private.
- Podcast enclosure URLs contain the feed token and random media identifiers.
- Treat the feed URL as a password.

## Supported audio

MP3, M4A/audio MP4, AAC, WAV, FLAC, OGG, and OPUS.

## License

MIT. Fork it, modify it, deploy your own copy, or build another interface around it.
