# Escape Pod Cast development status

Updated for 0.7.1. The supported targets remain macOS 11.7.11 and 15.x, Intel and Apple Silicon.

0.7.1 adds measured phase progress bars/percentages, cooperative abort with child-process-group shutdown and temporary-directory cleanup, retry of aborted imports, and confirmed abort-and-delete/import deletion. The final feed transaction is protected against interruption. A completed orphan upload can remain until the regular managed retention cleanup.

## Implemented in this development pass

1. Episode lifecycle records: uploaded/feed updating, exact GUID + enclosure confirmation in public RSS, available, expiry due, expired, removal pending, removed. Availability does not claim an iPhone download. Earlier history is explicitly unverified.
2. Persistent pause/resume and bounded transient retries (30, 120, 300 seconds), visible countdown, manual retry reset. Permission, certificate and conversion failures require attention. An upload already running finishes.
3. Unified intake validation and cross-process waiting/running deduplication, including saved YouTube links versus URL forms; watched-folder failures persist rather than retrying indefinitely.
4. Complete app/runtime/LaunchAgent snapshots, restoration after installation failure, recovery of interrupted updates, and user-triggered rollback. Connections, originals, and activity remain outside the snapshot.
5. A downloadable unsigned setup .app ZIP, plus macOS CI regression/conversion tests, native AppleScript compilation, and versioned release packaging. Python/Tk is still required; setup offers the official installer.
6. Waiting/failed episode title + description editing, local preview in the Mac's default player, waiting-order controls, retry all, and explicitly confirmed published deletion. Feed removal precedes audio deletion.
7. Click/keyboard activation of the hatch, persistent tape-button selection/focus, explicit paused intake labels, full titles in details, and saved reduced-motion setting.
8. Bounded audio subprocesses, converter stderr details, redacted diagnostics with app/Python/Tcl/Tk versions, lifecycle/retry/transaction regression tests.

## Verification still requiring real Macs

- Finder multi-file drops, Safari/Chrome address/link drags, native clicking and repeated drags without crashes on both supported targets.
- Minimum-size layout, long Unicode filenames, keyboard-only operation, VoiceOver reading/control access, trackpad scrolling, and reduced motion.
- Clean downloaded setup-app launch under Gatekeeper, update/rollback with LaunchAgent running, sleep/wake and network interruption.
- Real YouTube import, GitHub Pages propagation, and iPhone subscription/download/playback after expiry.
- CI results are recorded by GitHub Actions; simulated compatibility tests do not replace these checks.

## Consider next (not enabled automatically)

- Selected-track transport strip with play/pause, duration and waveform; current local preview opens the default Mac player.
- Configurable recording-folder watch, including robust SuperCollider recording-completion detection.
- Optional loudness normalization and silence trimming, previewed and preserving originals.
- Multiple shows, or authenticated private hosting; private hosting changes the existing GitHub-only architecture.
- Bundle a tested Python/Tk runtime, sign and notarize the Mac app; requires a compatible distribution/runtime and Apple signing credentials.
- Safely reconcile/import older publication history with live feed metadata; do not match episodes on title alone.
- Richer byte-level upload/download progress, without fictitious percentages or assumptions about resumable GitHub uploads.
- Clear/archive old local activity and rotate logs without deleting originals.
- Edit metadata for an already-published episode through a dedicated confirmed action.

## Constraints

No extra account, paid service, application server, browser cookies or access-restriction bypass. The random GitHub feed is unlisted and publicly accessible, not authenticated private hosting. Source audio is preserved except for successful moves into the watched folder's Published subfolder. Automated cleanup follows asset creation + 14 days while the Mac is awake and connected.
