# Install Escape Pod Cast on your Mac

1. [Download the current version](https://github.com/udeudeude/Escape-Pod-Cast/archive/refs/heads/main.zip) and unzip it.
2. Double-click **START-HERE.command**.
3. Follow the Mac setup windows. No Terminal typing is required.

If you downloaded an earlier version without START-HERE.command, download the current version first. The new installer also replaces the old Install.command behavior with the same guided setup.

## What the windows ask you to do

For a new installation, choose **Create My Copy**. On the GitHub page that opens:

1. Sign in to your own GitHub account.
2. Choose your account as **Owner**, keep **Escape-Pod-Cast** as the name or choose another, and click **Create fork**.
3. Return to setup and enter the owner/repository shown at the top of your copy, for example `yourname/Escape-Pod-Cast`.

Choose **Use Existing** if you already have your own copy. An existing installation offers **Update**, with its repository already selected and its saved token reused.

If you already created a token, choose **Paste Token** and reuse it. Otherwise choose **Open GitHub**; the token page has the name, owner, expiration, and required permissions filled in. On GitHub:

1. Sign in if asked.
2. Under **Repository access**, choose **Only select repositories** and select the copy you just created.
3. Click **Generate token**, then copy the token.
4. Return to the Escape Pod Cast window, paste it into the hidden field, and click **Connect**.

The installer checks the connection, stores the token in Mac Keychain, creates the temporary audio release, configures GitHub Pages, generates your random feed address, and installs the app. Each copy gets its own address and starts without the original owner's episodes. Connection failures appear in a setup window with a retry option. **Try Again** keeps the same credential; choose **Replace Token** only when you need a different one. Reinstalling uses a still-working saved connection instead of asking you to create another credential, and keeps your feed address.

**Updating from the old predictable address:** choose **Update**. Your existing episodes and audio remain, but `/feed.xml` is removed and replaced with your random address. Follow the new link in Apple Podcasts; setup copies it to the clipboard. Allow a few minutes for GitHub Pages to publish the change. The app's **Copy podcast link** action uses the new address too.

GitHub requires authorization before your Mac can upload to your account. No other account or payment method is involved. The token is not placed in process command arguments, the repository, feed, or log. It expires after one year with the prefilled default; you can choose a different expiration on GitHub. Administration permission is used only to configure Pages. Normal publishing and cleanup need Contents access.

## Your first episode

After installation, click **Open App**, then **Add audio…** and choose a short audio file. You can also drop files onto the app icon, or keep it in your Dock.

The app's menu provides **Open drop folder**, **Copy podcast link**, and **Open publishing log**. The feed link is copied at the end of installation. On your iPhone:

1. Open **Apple Podcasts → Library → ••• → Follow a Show by URL**.
2. Paste the podcast link and enable automatic downloads for this show.
3. Confirm your first episode actually downloads and plays with the iPhone offline.

The installer checks whether the feed is online. If GitHub has not published it yet, it tells you to allow a few minutes. Apple may reject an empty feed; publish one episode first if that happens. Apple controls refresh timing.

## Add a YouTube episode

1. If you have an older app, download the current version, run **START-HERE.command**, and choose **Update**. Keep your existing repository and saved connection.
2. Open **Escape Pod Cast.app → Paste YouTube link…**, paste a link to one finished video, and click **Get Audio**.
3. On the first import, click **Enable** to install the free helpers. Downloads total about 90 MB; allow 400 MB of free disk space and a few minutes. No Terminal typing or extra account is needed.
4. Wait for the publication message, then refresh your show in Apple Podcasts.

The helpers support the requested **macOS 11.7.11 and 15.7** targets. Install/update the app separately on each Mac; the saved connection and helpers are local to that Mac. For one shared feed, use one publishing Mac at a time to avoid competing updates.

For dropping links, save a browser shortcut as `.webloc` or `.url`, or put just one YouTube URL into a plain-text `.txt` file. Drop that file onto the app or into **Drop Audio Here**. Choose **Set up / update YouTube…** once before using the folder for links. If dragging directly from a browser does nothing, use the paste action or a saved link file; direct URL dragging is not consistent across browsers.

Video titles become episode titles. Repeating a link does not create a duplicate while its audio remains online, even if the link's tracking or time parameters change. Audio is public on GitHub and expires after 14 days. Only use material you have permission to copy and publicly host. Playlists, current live streams, and restricted/sign-in-only videos are not supported; browser cookies and access restrictions are not bypassed.

If a normal public video fails, open the publishing log for its error. Check your connection, choose **Set up / update YouTube…**, then retry the link. A failed helper update leaves any working helpers in place. YouTube may still refuse a download. Videos without AAC/M4A audio cannot be imported by this feature; use a permitted local audio copy instead.

## If the installer does not open

If macOS blocks the downloaded command, check **System Settings → Privacy & Security** for **Open Anyway** and reopen it. On older macOS releases, the equivalent section is in System Preferences. If Finder opens the file as text or says it is not executable, open Terminal, type `bash `, drag START-HERE.command into the Terminal window, and press Return. This is a fallback for the downloaded file, not part of normal setup.

The only required local runtime is **Python 3**. If missing, the installer explains how to download it and opens [python.org](https://www.python.org/downloads/macos/). Install the macOS package, then reopen START-HERE.command. No Python packages are needed. GitHub requests use macOS curl, so setup does not depend on Python’s network proxy lookup or certificate installation.

## What is installed

The app is at `~/Applications/Escape Pod Cast.app`. Its program, watched folder, feed-address file, log, and optional YouTube helpers are in `~/Library/Application Support/Escape Pod Cast/`. A per-user job handles folder uploads and cleanup while your Mac is awake. The downloaded folder can be removed after successful installation.

Originals dropped onto the app are untouched. Successful watched-folder uploads move into its **Published** subfolder. Audio is removed from GitHub after 14 days, with cleanup catching up when the Mac wakes. Preserve important originals until you have verified Apple Podcasts' local retention behavior after remote expiry.

Your feed address contains 48 random hexadecimal characters and is not linked from the site's landing page. It resists guessing, but its path is visible in your **public** GitHub repository and the audio is public in Releases. This is an unlisted personal feed, not authenticated private storage. Nothing is submitted to Apple's catalog.

## If something fails

Open **Status.log** in the Application Support folder. Retry the original failed file after fixing the problem; a completed upload is reused. The watched folder leaves failed originals in place and retries automatically. Files successfully published from that folder move into its **Published** subfolder. Keep that subfolder or move originals elsewhere as you prefer; it is not automatically deleted.

1. **Token expired or GitHub rejected access:** run START-HERE.command to reconnect.
2. **Feed URL gives 404:** use the app's **Copy podcast link** action to get the current random address. Open your own repository's **Settings → Pages**, check main and /docs, then wait for publication. The old `/feed.xml` address stops working after migration.
3. **Audio conversion failed:** use a supported input or optionally install ffmpeg. If you already use Homebrew, `brew install ffmpeg` adds the converter and codec probe. Never publish an incompatible format merely by renaming its extension.
4. **HEAD or byte-range validation failed:** audio was not added to the feed. Retry; if it persists, investigate the host's delivery behavior before assuming Apple will accept it.
5. **Network unavailable:** leave the folder upload in place or retry the app drop later. The Mac must be awake and connected to publish or delete expired audio.
6. **Repeated identical audio:** identical files deduplicate while online. Rename alone does not create a new episode. Publish different bytes if a distinct episode is needed.

## Remove the local installation

Unload the per-user job in Terminal:

```sh
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.escapepodcast.publisher.plist"
```

Then remove the app, that LaunchAgents file, and the Escape Pod Cast Application Support folder after preserving any local originals you want. Delete the **Escape Pod Cast GitHub** credential in Keychain Access, and revoke its token in GitHub settings. Uninstalling stops remote cleanup; delete remaining temporary assets in the repository's **audio** release yourself if desired.

The previous server implementation is removed from the current GitHub branch. If you deployed it separately, this installer does not delete that remote service or storage bucket.
