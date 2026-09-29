# Focus 0.4.0

Local screen-time tracking and hourly limits for Omarchy Linux.

- Productive, neutral and consumption activity, with a global daily screen-time counter.
- Tracking schedules, timed pauses and configurable warnings/limit actions.
- Shared counters for linked apps and websites, manual groups and detachment.
- Seven-day history view, local CSV export and settings backup.
- Optional Chromium / Google Chrome extension for active-site tracking.

## Install

Follow the [README](https://github.com/NoFlairos/focus#installation).
The desktop widget requires the separately installed local helper and systemd user
service. The extension also needs native-host registration with its actual ID.
The browser ZIP is an unpacked distribution, not a Chrome Web Store listing.

Assets: source archive, Chrome extension archive and SHA256SUMS.

## Validation and limits

40 Python tests, browser enforcement tests, Qt panel integration and Omarchy
manifest validation pass. An isolated real Chromium/native-helper test verified
connection, disconnection, installation and removal. Full systemd session lifecycle
and end-to-end behavior on a fresh Omarchy desktop remain to be verified; see
[validation details](https://github.com/NoFlairos/focus/blob/main/release/VALIDATION.md).

Mapped windows can count even when covered by another window. Ambiguous browser
window titles are skipped. Merging historical usage adds existing totals; past
overlaps cannot be reconstructed. The default consumption limit action closes
the target window or active site tab; choose Notify or Keep open if preferred.

No analytics or remote tracking backend. [Privacy](https://noflairos.github.io/focus/privacy.html).
