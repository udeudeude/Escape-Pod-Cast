# Native Mac verification

Use an interactive desktop session on Big Sur 11.7.11 and a 15.x Mac. Keep original audio and use a dedicated test repository for destructive publication/expiry checks.

1. Download the Mac setup ZIP, unzip and open Escape Pod Cast Setup.app. Verify the ordinary launch and any Gatekeeper Open Anyway flow. Update the existing connection without entering a new token.
2. Pause the queue. Drop two audio files (one with spaces/emoji/braces), Add audio with the same source, and drop the same file onto the Dock icon. Confirm one waiting job per source. Drop a saved YouTube shortcut and paste the same video URL: confirm one waiting job. Unsupported items should not prevent good inputs being queued.
3. Click the hatch and open it with Tab/Return/Space. Select tapes, move with Up/Down and scroll with the trackpad. Check controls and the complete filename/description using VoiceOver. Resize to 650 × 680 and inspect the footer and tape rack.
4. Edit waiting metadata, change queue order, preview local audio, then resume. Interrupt internet access during an upload. Confirm the visible bounded retry countdown, pause/resume, exhaustion after three automatic retries, and manual Retry all. Original files must remain usable.
5. Confirm Feed updating precedes Available. Compare the public RSS GUID and enclosure, then follow on iPhone. Do not treat Available as proof Apple downloaded the audio.
6. Confirm a published deletion explicitly; verify feed removal before GitHub audio deletion and preservation of the original. Check rollback restores all three runtime files, the app and agent together.
7. Enable reduced motion: lamp should remain steady and hatch motion should stop. Repeat browser/Finder drags many times, including cancelled and invalid drags; there must be no Python/Tk abort.
8. Export diagnostics and inspect for tokens, feed addresses and home paths. Log messages can still contain titles: review before sharing.
9. Import a large file and long public YouTube video. Confirm copying/download/upload percentages advance separately and reset on phase changes; conversion/feed checks must not fabricate percentages. Abort during download, conversion and upload. Confirm work stops, temporary disk space is released, originals remain, Retry works, and Delete removes the import. Repeat with a watched-folder original: it must move to Not Published and not be re-enqueued. Delete a running import; it must disappear after cleanup. Try Abort at the final feed update: it should be disabled or explain that the transaction must finish first.

For developer GUI checks in an interactive Mac desktop session:

```sh
EPC_MAC_GUI_TESTS=1 python3 -m unittest discover -s tests -v
```

CI intentionally skips desktop GUI tests. It runs regression/conversion checks and actually compiles the AppleScript droplet on macOS. Real Big Sur/iPhone/Gatekeeper behavior remains a separate check.
