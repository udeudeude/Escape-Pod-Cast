# Escape Pod Cast

**Drop an audio file in a web page. It appears as a new episode in your own personal podcast.**

Escape Pod Cast is a small open-source machine for turning arbitrary audio into a private-by-secret-link podcast feed. You run your own copy, connect your own Cloudflare R2 bucket, and get your own feed.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/udeudeude/Escape-Pod-Cast)

## What it does

1. Sign into your password-protected uploader.
2. Drop one or several audio files.
3. Optionally edit the episode titles and notes.
4. Tap **Publish**.
5. The audio streams directly into your own R2 bucket.
6. The episode metadata is saved in that same bucket.
7. Your RSS feed immediately includes the new episode.
8. Subscribe to the feed once in Apple Podcasts, Overcast, Pocket Casts, or another podcast app.

The Render service itself stores nothing important. It can restart or redeploy without losing your library.

## Why bring your own R2?

Cloudflare R2's Standard tier currently includes a monthly free allowance of storage and requests and does not charge egress bandwidth. Each Escape Pod Cast owner supplies their own R2 account, so there is no shared central audio store and no Escape Pod Cast account system.

Your R2 credentials stay in your own hosting environment. They are never committed to this repository.

## Setup

See **[SETUP.md](SETUP.md)**. It walks through:

- creating an R2 bucket,
- making a public media URL,
- creating a bucket-scoped read/write API token,
- deploying this repository on Render's free web-service plan,
- pasting the five R2 values and choosing an uploader password,
- subscribing to your newly generated feed.

## Privacy model

- The uploader is protected with a password.
- Each installation gets a long random `FEED_TOKEN`.
- Episode object paths contain that token plus random identifiers.
- The feed URL should be treated as a password: anyone who possesses it can learn the episode URLs.
- R2's public `r2.dev` URL is the easiest no-domain setup, but Cloudflare describes it as a development URL and rate-limits it. A custom R2 domain can replace it later without changing how the app works.

## Storage model

R2 contains:

```
media/<feed-token>/<random-id>.mp3
private/<feed-token>/episodes.json
```

The metadata object is also behind an unguessable token path. The application accesses it through authenticated R2 API calls.

## Supported audio

MP3, M4A/audio MP4, AAC, WAV, FLAC, OGG, and OPUS.

## Local development

```sh
cp .env.example .env
# export the variables in .env
npm install
npm start
```

Node 20 or newer is required.

## License

MIT. Fork it, alter it, host it yourself, and make your own version.
