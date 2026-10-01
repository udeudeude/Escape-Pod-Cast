# Install Escape Pod Cast on your Mac

This setup uses your existing GitHub account. It costs nothing and asks for no payment method. You do not need Render, Backblaze, Apple Podcasts Connect, a custom domain, or a podcast-hosting account.

## 1. Download the tool

On your Mac, [download the repository ZIP](https://github.com/udeudeude/Escape-Pod-Cast/archive/refs/heads/main.zip) and unzip it. The installation copies the program into your Application Support folder, so the download folder can be removed afterward.

The only required local runtime is **Python 3**. If the installer says it is missing, install the macOS package from [python.org](https://www.python.org/downloads/macos/), then try again. No Python packages are needed. If it raises a certificate verification error, run the Python installer's **Install Certificates.command** from its Applications folder. Python should be supported by your installed macOS version.

## 2. Create a repository-restricted GitHub credential

Open [GitHub's new fine-grained token page](https://github.com/settings/personal-access-tokens/new).

1. Give it a name such as **Escape Pod Cast Mac**.
2. Choose an expiration appropriate for you. Expiration means you must replace it later; an expired token cannot publish or clean up audio.
3. Under **Repository access**, choose **Only select repositories**, then **Escape-Pod-Cast**.
4. Add these repository permissions: **Contents: Read and write**, **Pages: Read and write**, **Administration: Read and write**. Metadata read access is automatic. Administration is required by GitHub's endpoint that enables/configures Pages; the program uses it for that setup operation only.
5. Generate the token and copy it. Paste it only into the installer on your Mac, not into this chat.

The token is stored in macOS Keychain, not in the repository, feed, configuration file, command-line arguments, or log. You can revoke it from the same GitHub settings page. For stricter permissions after setup, remove Administration from the token; normal publishing and cleanup need Contents access. You would have to restore Administration to run setup again if Pages needs reconfiguration.

## 3. Run the installer

Open **Install.command** in the extracted folder. If macOS blocks it, use the system's **Open Anyway** option for this downloaded file. If Finder opens it as text or says it is not executable, open Terminal, type `bash `, drag **Install.command** into the Terminal window, and press Return.

1. Press Return to accept `udeudeude/Escape-Pod-Cast` as your repository.
2. Paste the GitHub token when asked. The terminal hides your input.
3. Approve any macOS Keychain prompt for this program.

The installer:

1. Confirms that your repository is public and uses `main`.
2. Creates a single **audio** release if needed.
3. Enables GitHub Pages from **main → /docs**.
4. Creates **Escape Pod Cast.app** in your personal Applications folder.
5. Installs a per-user folder monitor and cleanup job that starts on login.
6. Opens the app's location and your feed-address file, and copies the feed address to your clipboard.

You can drag the app into your Dock. Double-clicking it opens the watched folder. Dragging files onto the icon publishes them in the background.

Files and logs live in `~/Library/Application Support/Escape Pod Cast/`. Your app is `~/Applications/Escape Pod Cast.app`. The installation is per-user and does not need administrator privileges.

## 4. Follow it once on the iPhone

After a few minutes, open your feed address in a browser to confirm that Pages is serving XML rather than a missing-page error. For this repository, the address is:

`https://udeudeude.github.io/Escape-Pod-Cast/feed.xml`

On your iPhone:

1. Open **Apple Podcasts → Library → ••• → Follow a Show by URL**.
2. Paste the feed address. If Apple rejects the empty feed, publish your first short audio file and try again after Pages updates.
3. Enable automatic episode downloads for this show.

The feed is not submitted to Apple's catalog. Its contents and audio are publicly accessible through GitHub.

## 5. Test with one small audio file

Drop a short MP3 or M4A onto the app. Wait for its completion message. Check that the episode appears and actually downloads in Apple Podcasts. Apple controls refresh timing; check the show manually if automatic refresh has not happened yet.

Do not assume that seeing a title proves a download completed. Check that playback works with your iPhone offline. This first Mac/iPhone test also verifies the native app, your credential, Pages publication, release delivery, and Apple behavior together.

Before relying on two-week expiry for important recordings, save/download an episode, then test its survival after remote expiry. Apple Podcasts' local retention settings are separate from this tool's cleanup.

## If something fails

Open **Status.log** in the Application Support folder. Retry the original failed file after fixing the problem; a completed upload is reused. The watched folder leaves failed originals in place and retries automatically. Files successfully published from that folder move into its **Published** subfolder. Keep that subfolder or move originals elsewhere as you prefer; it is not automatically deleted.

1. **Token expired or GitHub rejected access:** run Install.command with a replacement credential.
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
