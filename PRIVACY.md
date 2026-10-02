# Focus privacy

Focus runs locally on Omarchy Linux. Its optional Chromium / Google Chrome
extension communicates only with the separately installed helper on your computer.
No analytics, ads, remote tracking server or third-party data sharing is used.

## Data

Focus reads visible window identifiers, titles and addresses. The extension sends
active tab domains, titles, tab/window IDs and window state. It also sends declared
site names from open tabs (`application-name` or `og:site_name`) and manifest URLs declared on the same host or a parent domain, without query
strings or fragments. Manifests are not fetched.
These declarations help identify related services. Background tabs do not accumulate
time. The extension does not read page bodies, form inputs,
passwords or cookies. Titles may contain personal information and are used only
in memory to match tabs to windows.

The helper stores app/site activity, screen time and settings: classifications,
quotas, schedules, pauses, warnings, groups, exclusions and discovered site names.
Declared application identity and subdomain rules are also stored locally.
Daily history is kept for up to 45 days; hourly usage for about three days.
Settings remain until deleted. Exports and backups are created only on request
and remain until you delete them, even after clearing history.

## Control

Pause stops counting and enforcement, but the browser bridge still sends local
metadata. Disable the extension to stop those messages. Uninstalling preserves
settings and history. To erase them, stop the helper and delete
`~/.config/focus-ratio` and `~/.local/state/focus-ratio` (or their XDG equivalents).
Exports in the state directory are deleted with it.

## Permissions

- `tabs`: identify active sites and match their titles to visible windows.
- `nativeMessaging`: communicate with the local helper.
- HTTP/HTTPS content scripts: read declared site identity for labels and grouping.

Browsing data is used only for tracking and limits. Focus follows the Chrome Web
Store User Data Policy, including its Limited Use requirements.
