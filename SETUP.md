# Install Escape Pod Cast on your Mac

1. [Download the current version](https://github.com/udeudeude/Escape-Pod-Cast/archive/refs/heads/main.zip) and unzip it.
2. Double-click **START-HERE.command**.
3. Follow the Mac setup windows. No Terminal typing is required.

If you downloaded an earlier version without START-HERE.command, download the current version first. The new installer also replaces the old Install.command behavior with the same guided setup.

## What the windows ask you to do

For a new installation, choose **Create My Copy**. On the GitHub page that opens:

1. Sign in to your own GitHub account.
2. Choose your account as **Owner**, keep **Escape-Pod-Cast** as the name or choose another, and click **Create fork**.
3. Return to setup and paste the link to your new GitHub copy. You can also enter `yourname/Escape-Pod-Cast`.

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

After installation, click **Open App**, then **Add audio…** and choose a short audio file. You can also drop files onto the app icon, or keep it in your Dock. The app opens a single window with audio controls, a YouTube link field, recent activity, and current progress.

Watch the selected item's stage and elapsed time. **Published** means the audio and feed update are ready; Apple controls when it downloads. Failures show their cause and a recovery step beside **Retry selected item**. Other queued items continue. Closing the window does not cancel publishing; queued items are saved and resume while the Mac is awake and connected.

Click **Connect iPhone…** to copy the podcast link and see the steps. On your iPhone:

1. Open **Apple Podcasts → Library → ••• → Follow a Show by URL**.
2. Paste the podcast link and enable automatic downloads for this show.
3. Confirm your first episode actually downloads and plays with the iPhone offline.

The installer checks whether the feed is online. If GitHub has not published it yet, it tells you to allow a few minutes. Apple may reject an empty feed; publish one episode first if that happens. Apple controls refresh timing.

## Add a YouTube episode

1. If you have an older app, download the current version, run **START-HERE.command**, and choose **Update**. Keep your existing repository and saved connection.
2. Open **Escape Pod Cast.app**, paste a link to one finished video into **YouTube video link**, and click **Get audio**. The **Paste** button inserts the copied URL.
3. On the first import, click **Enable** to install the free helpers. Downloads total about 90 MB; allow 400 MB of free disk space and a few minutes. No Terminal typing or extra account is needed.
4. Wait for the publication message, then refresh your show in Apple Podcasts.

The helpers support the requested **macOS 11.7.11 and 15.7** targets. Install/update the app separately on each Mac; the saved connection and helpers are local to that Mac. For one shared feed, use one publishing Mac at a time to avoid competing updates.

For dropping links, save a browser shortcut as `.webloc` or `.url`, or put just one YouTube URL into a plain-text `.txt` file. Drop that file onto the app icon or into **Drop Audio Here**. Choose **Settings & help… → Set up / update YouTube…** once before using the folder for links. If dragging directly from a browser does nothing, use the paste field or a saved link file; direct URL dragging is not consistent across browsers. Drop onto the Dock/Finder app icon, rather than inside the window.

Video titles become episode titles. Repeating a link does not create a duplicate while its audio remains online, even if the link's tracking or time parameters change. Audio is public on GitHub and expires after 14 days. Only use material you have permission to copy and publicly host. Playlists, current live streams, and restricted/sign-in-only videos are not supported; browser cookies and access restrictions are not bypassed.

If a normal public video fails, select it to see the error. Check your connection, choose **Settings → Set up / update YouTube…**, then click **Retry selected item**. A failed helper update leaves any working helpers in place. Already-current versions are not downloaded again. YouTube may still refuse a download. Videos without AAC/M4A audio cannot be imported by this feature; use a permitted local audio copy instead.

## Settings, updates, and the optional folder

**Settings & help…** provides:

1. **Check connection & feed** — verifies that GitHub and your public podcast feed can be reached.
2. **Reconnect GitHub…** — opens the guided setup, keeping a working saved connection.
3. **Set up / update YouTube…** — installs or refreshes the optional helpers.
4. **Update this app…** — downloads the official update and opens setup. Choose **Update**. Your episodes, address, activity, and saved connection are kept. The window reopens after successful setup; cancelling keeps the current app.
5. **Open drop folder** and **Open detailed publishing log** — optional folder intake and technical details.

Files in **Drop Audio Here** publish after settling for about a minute. Success moves the original into **Published**. A failed original stays in place for automatic retry and appears in Recent activity. **Remove from queue** removes a waiting/failed task; for drop-folder items it keeps the original in **Not Published**, preventing repeated attempts. Move it back when ready. Nothing is deleted from your existing podcast by that action.

## If the installer does not open

If macOS blocks the downloaded command, check **System Settings → Privacy & Security** for **Open Anyway** and reopen it. On older macOS releases, the equivalent section is in System Preferences. If Finder opens the file as text or says it is not executable, open Terminal, type `bash `, drag START-HERE.command into the Terminal window, and press Return. This is a fallback for the downloaded file, not part of normal setup.

The only required local runtime is **Python 3**. If missing, the installer explains how to download it and opens [python.org](https://www.python.org/downloads/macos/). Install the macOS package, then reopen START-HERE.command. That official package includes the window toolkit. If an existing command-line Python lacks it, setup offers **Get Python** or **Use Simple App** to keep the old native menus. No Python packages are needed. GitHub requests use macOS curl, so setup does not depend on Python’s network proxy lookup or certificate installation.

## What is installed

The app is at `~/Applications/Escape Pod Cast.app`. Its program, watched folder, feed-address file, saved queue/activity, log, and optional YouTube helpers are in `~/Library/Application Support/Escape Pod Cast/`. A per-user job handles queued work, folder uploads, and cleanup while your Mac is awake. The downloaded folder can be removed after successful installation; reconnect and update are available inside the installed app.

Originals dropped onto the app are untouched. Successful watched-folder uploads move into its **Published** subfolder. Audio is removed from GitHub after 14 days, with cleanup catching up when the Mac wakes. Preserve important originals until you have verified Apple Podcasts' local retention behavior after remote expiry.

Your feed address contains 48 random hexadecimal characters and is not linked from the site's landing page. It resists guessing, but its path is visible in your **public** GitHub repository and the audio is public in Releases. This is an unlisted personal feed, not authenticated private storage. Nothing is submitted to Apple's catalog.

## If something fails

Select the failed item in **Recent activity**. Its error and next step appear below; click **Retry selected item** after addressing it. A completed upload is reused. A task interrupted by a stopped process is marked for retry when the app next opens. Detailed diagnostics are under **Settings → Open detailed publishing log**; ordinary retry does not require finding a log file.

1. **Token expired or GitHub rejected access:** choose **Settings → Reconnect GitHub…**.
2. **Feed URL gives 404:** click **Copy podcast link** to get the current random address, then try **Settings → Check connection & feed**. GitHub Pages may need a few minutes after setup. The old `/feed.xml` address stops working after migration.
3. **Audio conversion failed:** use a supported input or optionally install ffmpeg. If you already use Homebrew, `brew install ffmpeg` adds the converter and codec probe. Never publish an incompatible format merely by renaming its extension.
4. **HEAD or byte-range validation failed:** audio was not added to the feed. Retry; if it persists, investigate the host's delivery behavior before assuming Apple will accept it.
5. **Network unavailable:** click **Retry selected item** once connected. A fresh token is not needed merely because the network failed. The Mac must be awake and connected to publish or delete expired audio.
6. **Repeated identical audio:** identical files deduplicate while online. Rename alone does not create a new episode. Publish different bytes if a distinct episode is needed.

## Remove the local installation

Unload the per-user job in Terminal:

```sh
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.escapepodcast.publisher.plist"
```

Then remove the app, that LaunchAgents file, and the Escape Pod Cast Application Support folder after preserving any local originals you want. Delete the **Escape Pod Cast GitHub** credential in Keychain Access, and revoke its token in GitHub settings. Uninstalling stops remote cleanup; delete remaining temporary assets in the repository's **audio** release yourself if desired.

The previous server implementation is removed from the current GitHub branch. If you deployed it separately, this installer does not delete that remote service or storage bucket.
