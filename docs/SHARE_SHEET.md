# iPhone Share menu integration

The web application accepts a shared address through its `url` query parameter. iOS does not automatically register a website as a native Share destination. A personal Shortcut provides the integration without an App Store application.

## Set up on iPhone

1. Open **Shortcuts** and create a shortcut named **Escape Pod Cast**.
2. Open the shortcut's details and enable **Show in Share Sheet**.
3. Set the accepted input to **URLs** and **Safari webpages**.
4. Add the **URL Encode** action, using **Shortcut Input**.
5. Add a **Text** action containing `https://udeudeude.github.io/Escape-Pod-Cast/app/?url=` followed by the encoded input variable.
6. Add **Open URLs** using that text.
7. Save. In Safari, share an audio link or webpage and choose **Escape Pod Cast**.

The shortcut opens the application's import screen with the link populated. Publishing still requires confirmation.

For local audio files, use the application's **Choose an audio file** control in Safari or the Files app. The above shortcut is for URLs, not binary file transfer.

## Security

Never include the GitHub token in the Shortcut URL. The token remains in the application's browser session or the user's Passwords app. The URL query string may be visible in browser history, so do not share private signed URLs containing credentials.
