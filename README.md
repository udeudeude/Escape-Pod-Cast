# Escape Pod Cast

**Drop audio onto a Mac app. It becomes an episode in Apple Podcasts on your iPhone.**

Your Mac prepares the audio and updates a static feed. Your existing GitHub account hosts the feed on Pages and the temporary audio as Release assets. No application server, database, storage provider, additional account, or payment method.

[Download](https://github.com/udeudeude/Escape-Pod-Cast/archive/refs/heads/main.zip), unzip, and double-click **START-HERE.command**. New users choose **Create My Copy**: setup opens GitHub's fork page, then connects their own copy. Existing installations choose **Update** and reuse their saved connection. Setup handles app installation and gives each repository its own random podcast address. [More setup help →](SETUP.md)

## Everyday use

1. Open **Escape Pod Cast.app** and click **Add audio…**, or drop files onto its Dock/Finder icon.
2. Watch the current stage and activity list in the app. Add more items whenever you like; they wait their turn.
3. When an item says **Published**, refresh your show in Apple Podcasts. Enable automatic downloads on the iPhone.

The single window shows preparation, conversion, downloads, upload, playback checks, and feed updates, with an animated indicator and elapsed time. The indicator shows that a task is active; it is not an invented percentage. Failures include the actual problem and a next step beside **Retry selected item**. Successful items stay published when another item fails. Queue and activity records survive closing the window or restarting the Mac. The folder monitor resumes queued items while the Mac is awake and connected.

**Connect iPhone…** copies the podcast link and gives the subscription steps. **Settings & help…** includes connection/feed checks, reconnection, YouTube helper updates, app updates, and the detailed log. **Update this app…** downloads the current official code and opens setup; choose **Update** to keep the saved connection, episodes, address, and activity. After successful setup the window reopens with the updated app. Cancelling setup keeps the current app. The update is pinned to one GitHub commit and extracts only known app files. No Terminal typing or manually unzipping is needed for subsequent updates.

The optional **Open drop folder** action in Settings opens **Drop Audio Here**. Folder uploads settle for about a minute; successful originals move into **Published**. Folder activity appears in the same window. Direct app drops leave originals untouched. Titles come from filenames. **Remove from queue** works on waiting/failed items. For a failed drop-folder item it keeps the original in **Not Published**, stopping automatic retries; move it back when ready. It does not delete published audio. Work already publishing is allowed to finish.

## YouTube audio

Open the app, paste one video URL into **YouTube video link** (or click **Paste**), and click **Get audio**. The first import offers to download two free helpers, **yt-dlp** and **Node 22**, into the app's own folder. No extra account, payment, Homebrew, administrator access, or Terminal typing is needed. Downloads total about 90 MB; allow 400 MB of free disk space and a few minutes on a slow connection. Ordinary audio publishing does not need these helpers.

You can also drop a saved YouTube `.webloc` or `.url` shortcut, or a `.txt` file containing just one video URL, onto the app icon or into **Drop Audio Here**. Enable the helpers from Settings before using the watched folder. Browser URL drags vary between browsers and macOS versions; if a direct drag is ignored, save/drop a link file or use the URL field. Dropping onto the window itself is not supported; use the app icon. Playlists are not imported; a video link containing a playlist parameter imports only that video.

Episodes use the video's title. Different links to the same video deduplicate while its audio is online, and a retry after a failed feed update reuses the completed upload. Temporary downloaded audio is removed afterward. The same 14-day expiry applies. **Settings → Set up / update YouTube…** refreshes the helpers when YouTube changes; failed downloads or compatibility checks leave the previous working helpers active. Already-current helpers are not downloaded again. Successful updates keep one previous working helper bundle and remove older complete helper folders.

The compatibility target is **macOS 11.7.11 (Big Sur) and 15.7**, on Intel or Apple Silicon. Node stays on the 22 release line because its official Mac binaries support macOS 11; installing a newer major automatically could break Big Sur. The official yt-dlp Mac executable includes its Python runtime and JavaScript solver scripts. Downloads are checked against the official SHA-256 values before execution, and both helpers must start successfully before becoming active. See [Node 22 platform requirements](https://github.com/nodejs/node/blob/v22.x/BUILDING.md) and [yt-dlp's runtime requirements](https://github.com/yt-dlp/yt-dlp/wiki/EJS).

Only import audio you have permission to copy and **publicly host**. Support is limited to accessible, finished videos with AAC/M4A audio; live/upcoming streams, members-only/private/age-restricted videos, sign-in requirements, and YouTube blocks are not bypassed. No browser cookies or credentials are read. The app ignores external yt-dlp settings/plugins and does not fetch extra executable components during import. If a video has no compatible audio stream, import a permitted local audio copy instead. YouTube availability is not guaranteed.

## Three participants

| Participant | Job |
| --- | --- |
| Mac | File intake, audio preparation, feed update, upload, cleanup |
| GitHub | Pages serves the feed at a random address; one `audio` release holds temporary audio |
| iPhone / Apple Podcasts | Follows the feed URL directly and downloads episodes |

The local program needs Python 3 and uses its standard library, including Tk for the app window. The official python.org Mac package includes that toolkit. Setup prefers an installed Python with it. If the toolkit is missing, setup offers the official download or **Use Simple App** with the older native menus. No Python packages, Git commands, GitHub command-line tool, or web application is needed for everyday use. macOS provides the app compiler, Keychain credential storage, audio converter, and scheduled folder monitor. Network requests on macOS use the included curl tool. Optional ffmpeg expands supported audio formats.

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

Run `python3 -m unittest discover -s tests -v` for feed, retry, cleanup, delivery-validation, conversion, setup-boundary, Mac network transport, YouTube, durable queue, recovery, cancellation, and update tests. GUI tests run when a display is available, otherwise they are explicitly skipped. Conversion tests need ffmpeg and ffprobe; the publisher itself does not require them on macOS. The window, native droplet, and Keychain integration must be verified on a Mac, followed by an actual YouTube import and iPhone download/playback test. Automated tests simulate Mac 11.7.11 and 15.7 helper setup; this is not a claim that those Macs have been tested here.

The obsolete Node server, browser uploader, Render blueprint, object-storage dependencies, and storage configuration were removed from the current branch. Historical commits remain intact. No old Releases or Actions runs existed during migration. Removing repository files does not close a separately deployed Render service or delete a Backblaze account/bucket.

## Independent copies

The same download is for every Mac user. The installer guides **Create My Copy**, or **Use Existing** for a repository already created. You can paste the full GitHub repository link instead of typing owner/repository. It never defaults a new user to the author's publishing repository. A fork gets a new random address and a feed without the parent's copied episodes. Each person's repository, audio, and credential operate independently. There is no shared service operated by the author. Install on either supported Mac and connect the same personal repository to use the same feed; queues, history, and Keychain connections remain local to each Mac. Publish from one Mac at a time. A competing feed update fails safely and can be retried. This distribution currently supports macOS.

MIT license.
