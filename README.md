# Escape Pod Cast

**Drop audio onto a Mac app. It becomes an episode in Apple Podcasts on your iPhone.**

Your Mac prepares the audio and updates a static feed. Your existing GitHub account hosts the feed on Pages and the temporary audio as Release assets. No application server, database, storage provider, additional account, or payment method.

[Download](https://github.com/udeudeude/Escape-Pod-Cast/archive/refs/heads/main.zip), unzip, and double-click **START-HERE.command**. The guided Mac setup opens GitHub with permission fields filled in and handles the connection, app installation, and feed setup. [More setup help →](SETUP.md)

## Everyday use

1. Drop one or several files onto **Escape Pod Cast.app**, optionally kept in your Dock.
2. The app uploads in the background and confirms publication, or tells you where to find an error.
3. Apple Podcasts fetches the new episode on its next refresh, with automatic downloads enabled.

Opening the app also offers **Add audio…**, **Open drop folder**, **Copy podcast link**, and **Open publishing log**. Choose **Open drop folder** to use **Drop Audio Here**. The folder monitor publishes files after they have settled for about a minute, moving successful originals into **Published**. Direct app drops leave originals untouched. Titles come from filenames. There is no mandatory title editor or Publish button.

## Three participants

| Participant | Job |
| --- | --- |
| Mac | File intake, audio preparation, feed update, upload, cleanup |
| GitHub | Pages serves `feed.xml`; one `audio` release holds temporary audio |
| iPhone / Apple Podcasts | Follows the feed URL directly and downloads episodes |

The local program needs Python 3 and uses its standard library. No package installation, Git commands, GitHub command-line tool, or web application is needed for everyday use. macOS provides the app compiler, Keychain credential storage, audio converter, and scheduled folder monitor. Optional ffmpeg expands supported audio formats.

## Audio and retention

MP3 and AAC-encoded M4A pass through when their codec is verified. Other readable formats convert locally to AAC-encoded M4A. An M4A containing Apple Lossless is converted too: its extension alone does not prove compatibility. macOS handles common formats; install ffmpeg for formats it cannot read, such as some Ogg/Opus files. Uploads must be smaller than 2 GiB after conversion.

The publisher checks the **public enclosure URL** with a HEAD request and a real byte-range request before adding the episode to the feed. Completed uploads are reused when retrying a failed feed update. A duplicate copy of the same source file does not create a second episode while its asset remains online.

After 14 days, cleanup removes the feed item and deletes its Release asset. It runs about hourly while your Mac is awake, and catches up after sleep or a network outage. Failed/unreferenced uploads also expire. Only assets matching this tool's managed naming convention are deleted; unrelated Release assets are left alone. Source audio never enters Git history. Feed metadata does enter public Git history.

**Apple Podcasts controls refresh and local retention.** Publication does not guarantee an immediate download. Enable automatic downloads and preserve important originals yourself until testing confirms that saved/downloaded episodes remain usable after remote expiry. This tool is not an archive.

## Visibility

This is an **unlisted, publicly accessible personal feed**, not an authenticated private feed. Anyone who browses the public repository can read the feed and find the audio. A random URL in a public repository would not fix that. `itunes:block` prevents catalog processing; it does not restrict file access. Nothing is submitted to Apple Podcasts Connect.

## Testing and scope

Run `python3 -m unittest discover -s tests -v` for feed, retry, cleanup, delivery-validation, conversion, and setup-boundary tests. Conversion tests need ffmpeg and ffprobe; the publisher itself does not require them on macOS. The native droplet and Keychain integration must be verified on a Mac, followed by an actual iPhone subscription/download test.

The obsolete Node server, browser uploader, Render blueprint, object-storage dependencies, and storage configuration were removed from the current branch. Historical commits remain intact. No old Releases or Actions runs existed during migration. Removing repository files does not close a separately deployed Render service or delete a Backblaze account/bucket.

## Independent copies

For someone else's installation, fork this repository, use that public fork during setup, and follow its feed URL. Each person's Mac and GitHub account operate independently. There is no shared service operated by the author. Use one publishing Mac per feed.

MIT license.
