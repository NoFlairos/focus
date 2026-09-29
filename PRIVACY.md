# Focus privacy

Focus is a local activity tracker for Linux with Omarchy. Its optional
Chromium / Google Chrome extension connects to the separately installed local
helper. It does not provide tracking on other operating systems.

## Information handled

The helper reads visible window application identifiers, titles and addresses.
The extension reads active tab domains, titles, tab/window identifiers and
window state. A content script reads declared service names from
`application-name` or `og:site_name` metadata. It does not read page bodies,
form inputs, passwords or cookies. Titles can contain personal information;
they are used in memory to match tabs with desktop windows.

The helper stores daily activity by app/site, hourly quota usage, daily screen
time, classifications, schedules, group links and discovered service names.
Pause expiration, warning preferences, dismissed group suggestions and explicit
detachments are also stored as settings. These files stay in the user's Focus configuration and state directories.
No analytics, advertisements, remote backend or third-party data sharing is used.
The extension communicates only with the native helper on this computer.

Daily history is retained for up to 45 days; hourly usage for approximately
three days. Settings, group links and discovered site names remain until their
files are deleted. Pause stops time accumulation and limit enforcement; it does
not disconnect the browser bridge or stop its local metadata messages.

## Control and deletion

Tracking days, hours, pause, categories, exclusions, quotas and groups are
managed in the desktop panel. Disabling the extension stops its messages.
Uninstallation stops the helper but preserves settings/history intentionally.
After stopping the helper, delete `~/.config/focus-ratio` and
`~/.local/state/focus-ratio` to erase stored data (or their XDG equivalents).

Exports and settings backups are created only on request, in the local
`exports` subdirectory. They remain until deleted, including after clearing
the active history. Copying or sharing exported files is controlled by you.

## Browser permissions

- `tabs`: match active tab titles and domains to visible desktop windows.
- `nativeMessaging`: communicate with the local Focus helper.
- HTTP/HTTPS content-script access: read the site's declared name for clear
  labels. The domain remains the identifier; matching names never merge sites.

Browsing data is used only to provide the visible tracking and limit features.
Focus's use of this data follows the Chrome Web Store User Data Policy,
including the Limited Use requirements.
