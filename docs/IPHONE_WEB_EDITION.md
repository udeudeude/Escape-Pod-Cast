# iPhone-first web edition: implementation contract

Status: design baseline, not a claim of a working web release.

## Goal
Publish and manage personal podcast episodes entirely from an iPhone, with no Mac running. Keep the existing GitHub Pages feed, Release-asset hosting, episode identifiers, and 14-day retention semantics.

## Source findings
- The current Mac edition performs intake, local conversion, YouTube extraction, GitHub Release upload, feed publication, and cleanup.
- Its Python/Tk interface and macOS conversion and Keychain dependencies cannot execute inside iPhone Safari.
- The Orchestral Maneuvers feed used remotely hosted audio references, showing that an RSS enclosure need not be rehosted if its source is stable and supports podcast clients.

## Two publishing paths
1. **Remote enclosure:** Validate that the URL is a directly playable, public, durable audio resource, with a supported content type, byte-range access, and known length. Only then write its URL as the enclosure. Do not mistake a webpage or HLS playlist for an audio file.
2. **Managed upload:** For local files, inaccessible/unstable links, and YouTube, stage audio and process it in a GitHub Actions worker, then publish the Release asset URL.

## Authentication and security
- Never embed a GitHub token, personal access token, or Actions secret in a publicly served web app.
- Use a GitHub OAuth authorization flow appropriate for a public browser client, with narrow repository permissions and explicit revocation. A browser-only app cannot safely hold a long-lived GitHub credential.
- No unauthenticated endpoint may trigger arbitrary URL fetching with privileged GitHub credentials. Validate URLs and redirects; reject private, loopback, link-local, and metadata endpoints at every hop.
- Treat remote titles and metadata as untrusted text; escape output in HTML and XML.
- The existing unlisted feed is publicly discoverable in repository history; do not describe it as authenticated private hosting.

## iPhone intake
- Provide a responsive installed-web-app interface with paste URL, choose audio file, queue, status, retry, deletion, and subscription link.
- Support the iOS Share menu through a Shortcuts share-sheet action that opens a URL-encoded import deep link, or another verified share extension. Do not claim that a normal home-screen web app automatically registers as a native Share destination.
- Never publish automatically from merely opening an untrusted URL; require explicit confirmation.
- For large local uploads, use a transfer route with actual resumability and capacity limits. GitHub Actions workflow_dispatch inputs are not a binary file-upload mechanism.

## Worker design
- Move reusable feed serialization, lifecycle, retention, and asset-management code into platform-neutral Python modules.
- Run YouTube extraction and audio conversion in GitHub Actions with pinned, integrity-checked tooling and explicit time/size limits.
- Use concurrency control and optimistic repository revision checks to avoid clobbering feed updates.
- Run cleanup on a scheduled GitHub Action so expiry does not depend on the Mac being awake.
- Publish only after confirming the public audio URL is reachable; report Apple Podcasts refresh separately.

## Compatibility
- Preserve existing feed URL and GUIDs during migration.
- Retain the Mac edition as an optional client; avoid two independent publishers racing on feed state.
- Do not import copyrighted or access-restricted content without appropriate permission.

## Required acceptance tests
1. iPhone-only direct audio URL -> feed item -> actual Apple Podcasts playback.
2. iPhone-only YouTube URL -> worker extraction -> Release upload -> playback.
3. iPhone Files audio upload -> playback, including a large-file interruption/retry test.
4. Share-sheet shortcut -> populated confirmation screen.
5. Fourteen-day scheduled cleanup while all personal computers are off.
6. Unauthorized requests cannot publish, read secrets, or fetch internal URLs.
7. Existing subscribers and episode GUIDs survive migration.

## Deployment caveat
This document is a specification. None of the above web workflows is represented as implemented until its code, deployment, and end-to-end tests exist.
