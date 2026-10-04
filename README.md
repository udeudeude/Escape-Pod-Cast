# Escape Pod Cast

**Drop audio onto a Mac app. It becomes an episode in Apple Podcasts on your iPhone.**

Your Mac prepares the audio and updates a static feed. Your existing GitHub account hosts the feed on Pages and the temporary audio as Release assets. No application server, database, storage provider, additional account, or payment method.

[Download](https://github.com/udeudeude/Escape-Pod-Cast/archive/refs/heads/main.zip), unzip, and double-click **START-HERE.command**. New users choose **Create My Copy**: setup opens GitHub's fork page, then connects their own copy. Existing installations choose **Update** and reuse their saved connection. Setup handles app installation and gives each repository its own random podcast address. [More setup help →](SETUP.md)

## Everyday use

1. Drop one or several files onto **Escape Pod Cast.app**, optionally kept in your Dock.
2. The app uploads in the background and confirms publication, or tells you where to find an error.
3. Apple Podcasts fetches the new episode on its next refresh, with automatic downloads enabled.

Opening the app also offers **Add audio…**, **Open drop folder**, **Copy podcast link**, and **Open publishing log**. Choose **Open drop folder** to use **Drop Audio Here**. The folder monitor publishes files after they have settled for about a minute, moving successful originals into **Published**. Direct app drops leave originals untouched. Titles come from filenames. There is no mandatory title editor or Publish button.

## Three participants

| Participant | Job |
| --- | --- |
| Mac | File intake, audio preparation, feed update, upload, cleanup |
| GitHub | Pages serves the feed at a random address; one `audio` release holds temporary audio |
| iPhone / Apple Podcasts | Follows the feed URL directly and downloads episodes |

The local program needs Python 3 and uses its standard library. No package installation, Git commands, GitHub command-line tool, or web application is needed for everyday use. macOS provides the app compiler, Keychain credential storage, audio converter, and scheduled folder monitor. Network requests on macOS use the included curl tool, keeping setup and publishing on the same network path. Optional ffmpeg expands supported audio formats.

## Audio and retention

MP3 and AAC-encoded M4A pass through when their codec is verified. Other readable formats convert locally to AAC-encoded M4A. An M4A containing Apple Lossless is converted too: its extension alone does not prove compatibility. macOS handles common formats; install ffmpeg for formats it cannot read, such as some Ogg/Opus files. Uploads must be smaller than 2 GiB after conversion.

The publisher checks the **public enclosure URL** with a HEAD request and a real byte-range request before adding the episode to the feed. Completed uploads are reused when retrying a failed feed update. A duplicate copy of the same source file does not create a second episode while its asset remains online.

After 14 days, cleanup removes the feed item and deletes its Release asset. It runs about hourly while your Mac is awake, and catches up after sleep or a network outage. Failed/unreferenced uploads also expire. Only assets matching this tool's managed naming convention are deleted; unrelated Release assets are left alone. Source audio never enters Git history. Feed metadata does enter public Git history.

**Apple Podcasts controls refresh and local retention.** Publication does not guarantee an immediate download. Enable automatic downloads and preserve important originals yourself until testing confirms that saved/downloaded episodes remain usable after remote expiry. This tool is not an archive.

## Visibility

Each repository gets a stable address of the form `https://owner.github.io/repository/feeds/<48 random hexadecimal characters>/feed.xml`, generated with 192 bits of randomness. It resists guessing. Setup does not publish a feed link on the site's landing page; use the app's **Copy podcast link** action. Reinstalling keeps the same address.

This is an **unlisted, publicly accessible personal feed**, not an authenticated private feed. The address and feed are visible in the public repository, and Release assets are public. Anyone browsing GitHub can find them; randomness does not provide secrecy from that person. `itunes:block` prevents catalog processing; it does not restrict file access. Nothing is submitted to Apple Podcasts Connect.

Updating an older installation migrates its episodes and removes the predictable `/feed.xml` file in one commit. Follow the new address in Apple Podcasts afterward. Its episodes keep their identifiers and audio URLs. A concurrent publisher prevents migration from overwriting its changes; retry setup. Historical commits remain publicly accessible.

## Testing and scope

Run `python3 -m unittest discover -s tests -v` for feed, retry, cleanup, delivery-validation, conversion, setup-boundary, and Mac network transport tests. Conversion tests need ffmpeg and ffprobe; the publisher itself does not require them on macOS. The native droplet and Keychain integration must be verified on a Mac, followed by an actual iPhone subscription/download test.

The obsolete Node server, browser uploader, Render blueprint, object-storage dependencies, and storage configuration were removed from the current branch. Historical commits remain intact. No old Releases or Actions runs existed during migration. Removing repository files does not close a separately deployed Render service or delete a Backblaze account/bucket.

## Independent copies

The same download is for every Mac user. The installer guides **Create My Copy**, or **Use Existing** for a repository already created. It never defaults a new user to the author's publishing repository. A fork gets a new random address and a feed without the parent's copied episodes. Each person's Mac, GitHub repository, Release assets, and saved credential operate independently. There is no shared service operated by the author. Use one publishing Mac per feed. This distribution currently supports macOS.

MIT license.
