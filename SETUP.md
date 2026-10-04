# Install Escape Pod Cast on your Mac

1. [Download the current version](https://github.com/udeudeude/Escape-Pod-Cast/archive/refs/heads/main.zip) and unzip it.
2. Double-click **START-HERE.command**.
3. Follow the Mac setup windows. No Terminal typing is required.

If you downloaded an earlier version without START-HERE.command, download the current version first. The new installer also replaces the old Install.command behavior with the same guided setup.

## What the windows ask you to do

Click **Install**. Your repository is already selected. Use **Other Repository** only for an independent copy.

The installer opens GitHub's token page with the name, owner, expiration, and required permissions filled in. On GitHub:

1. Sign in if asked.
2. Under **Repository access**, choose **Only select repositories** and select **Escape-Pod-Cast**.
3. Click **Generate token**, then copy the token.
4. Return to the Escape Pod Cast window, paste it into the hidden field, and click **Connect**.

The installer checks the connection, stores the token in Mac Keychain, creates the temporary audio release, configures GitHub Pages, and installs the app. Connection failures appear in a setup window with a retry option. Reinstalling uses a still-working saved connection instead of asking you to create another credential.

GitHub requires authorization before your Mac can upload to your account. No other account or payment method is involved. The token is not placed in process command arguments, the repository, feed, or log. It expires after one year with the prefilled default; you can choose a different expiration on GitHub. Administration permission is used only to configure Pages. Normal publishing and cleanup need Contents access.

## Your first episode

After installation, click **Open App**, then **Add audio…** and choose a short audio file. You can also drop files onto the app icon, or keep it in your Dock.

The app's menu provides **Open drop folder**, **Copy podcast link**, and **Open publishing log**. The feed link is copied at the end of installation. On your iPhone:

1. Open **Apple Podcasts → Library → ••• → Follow a Show by URL**.
2. Paste the podcast link and enable automatic downloads for this show.
3. Confirm your first episode actually downloads and plays with the iPhone offline.

The installer checks whether the feed is online. If GitHub has not published it yet, it tells you to allow a few minutes. Apple may reject an empty feed; publish one episode first if that happens. Apple controls refresh timing.

## If the installer does not open

If macOS blocks the downloaded command, check **System Settings → Privacy & Security** for **Open Anyway** and reopen it. On older macOS releases, the equivalent section is in System Preferences. If Finder opens the file as text or says it is not executable, open Terminal, type `bash `, drag START-HERE.command into the Terminal window, and press Return. This is a fallback for the downloaded file, not part of normal setup.

The only required local runtime is **Python 3**. If missing, the installer explains how to download it and opens [python.org](https://www.python.org/downloads/macos/). Install the macOS package, then reopen START-HERE.command. No Python packages are needed. If Python reports a certificate error, run **Install Certificates.command** from its folder in Applications.

## What is installed

The app is at `~/Applications/Escape Pod Cast.app`. Its program, watched folder, feed-address file, and log are in `~/Library/Application Support/Escape Pod Cast/`. A per-user job handles folder uploads and cleanup while your Mac is awake. The downloaded folder can be removed after successful installation.

Originals dropped onto the app are untouched. Successful watched-folder uploads move into its **Published** subfolder. Audio is removed from GitHub after 14 days, with cleanup catching up when the Mac wakes. Preserve important originals until you have verified Apple Podcasts' local retention behavior after remote expiry.

The feed and audio are **publicly accessible** through GitHub. This is an unlisted personal feed, not authenticated private storage. Nothing is submitted to Apple's catalog.

## If something fails

Open **Status.log** in the Application Support folder. Retry the original failed file after fixing the problem; a completed upload is reused. The watched folder leaves failed originals in place and retries automatically. Files successfully published from that folder move into its **Published** subfolder. Keep that subfolder or move originals elsewhere as you prefer; it is not automatically deleted.

1. **Token expired or GitHub rejected access:** run START-HERE.command to reconnect.
2. **Feed URL gives 404:** check [Pages settings](https://github.com/udeudeude/Escape-Pod-Cast/settings/pages) for main and /docs, then wait for publication.
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
