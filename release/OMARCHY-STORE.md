# Omarchy — local submission draft

Name: Focus
Plugin ID: io.github.noflairos.focus-ratio
Version: 0.4.0
Category: Productivity
Suggested tags: productivity, screen-time, local, tracking
Repository and exact commit: pending GitHub preparation and publication approval.

Description:
Local screen-time tracking and hourly limits for visible apps and websites.
Classify activity, group services, set tracking hours and review the last seven days.

Installation disclosure:
The widget requires a separately installed local Python helper and a user systemd
service. Installing only the Omarchy widget does not start tracking. Follow
scripts/install-local.sh, then install and enable the widget as documented.
Website tracking additionally requires the browser extension and native-host
registration. This is not a one-click, self-contained plugin installation.

Capabilities for review:
- Reads visible Hyprland window metadata and session idle/lock state.
- Stores local SQLite activity history and JSON settings/state.
- Launches the helper CLI and can restart its user service from Diagnostics.
- Can close configured app windows and matching active site tabs at their limit.
- Can send local desktop notifications and export files on user request.
- No remote backend or network telemetry.

Previews: release/assets/panel-manage.png, panel-now.png and bar-focus.png.
These are pixel-preserving crops supplied by the user; see CAPTURES.md.
README, MIT license and manifest are included at the repository root.

Submission reference (checked 2026-09-29):
https://plugins.omarchy.org/publish.html
Recheck the linked issue form when submitting; send only after user approval.
