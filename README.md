# Focus

An Omarchy Quickshell plugin for a local, configurable productive/neutral/consumption
tracker with hourly budgets for visible consumption apps and websites.

## Preview

![Focus in the Omarchy bar](release/assets/bar-focus.png)

![Visible apps and shared site limits](release/assets/panel-now.png)
![Tracking schedule](release/assets/panel-manage.png)

## What it does

The local tracker reads visible Hyprland windows, supports per-target
classification and hourly consumption quotas, and exposes a Chromium
native-messaging bridge for visible active tabs. The compact bar widget shows
every tracked app or site on a displayed workspace. The Now panel shows only open targets; Review keeps
unclassified targets available, while Manage holds saved apps and sites so
roles and limits remain editable after their windows close. Review can exclude
apps and sites from tracking; Manage can restore them and edit tracking days
and hours. The panel also has
a pause control and a seven-day history view.

## Design constraints

- Screen time counts each tracked interval once, even when several apps or
  sites are visible. The daily counter survives restarts and respects the same
  schedule, pause, lock, idle, and exclusion rules as app tracking. The panel
  shows when today's recording began; older history has no screen-time total
  because past overlaps cannot be reconstructed. Per-app activity remains cumulative across visible targets. The
  activity bar shows productive, neutral, and consumption time in that order.
- English is the default UI language; strings should remain ready for future
  localization.
- Data stays on this computer.
- Budgets reset at the top of each clock hour. The default tracking schedule is
  weekdays, 08:00–17:00. In Manage, select the days, enter start and end times
  in 24-hour format, then choose Save. Overnight hours are
  supported; matching start and end times track the full selected day.
- Time counts for mapped windows on displayed workspaces, whether focused or
  not. Background tabs and windows on another workspace do not count. Hyprland
  does not expose dependable pixel-level occlusion for every client, so a
  mapped window may count even if another floating window fully covers it.
- The bar shows each visible target and highlights the one with focus. When
  there are many, its contents can scroll horizontally. Consumption targets
  also show their remaining hourly time. Tracking pauses when the session is locked or
  reports idle, and can also be paused manually in the panel.
- When a consumption target reaches its budget, the default action closes its
  app window or site tab until the next hour. Manage can instead send one
  notification per hour or keep the target open.
- App and domain categories are user-editable: Productive, Neutral, Consumption.
  New targets are unclassified until the user chooses a role. Their recorded
  time is assigned to the chosen role retroactively. Neutral is an explicit
  role without an hourly limit. An hourly Consumption
  limit starts counting when that role is chosen.
- An app and its website share one category and hourly limit when the helper
  can identify the same service. Chromium web-app windows are linked by their
  domain. Other desktop apps are linked through a URL in their launcher, when one is explicitly declared. Similar app names alone never trigger a merge.
  The app and site appear as one shared entry in Manage. If both already
  had settings, the site's settings take precedence; existing usage is added
  together. The browser extension is needed to track and close site tabs.
- Excluding a target in Review drops
  its unclassified history and stops future tracking until Track again is used.
- The helper runs as a user service, without root privileges. Data is local in
  `~/.config/focus-ratio/` and `~/.local/state/focus-ratio/`.

## Local setup

1. Install the local helper and user service:

   ```sh
   ./scripts/install-local.sh
   ```

2. Install a local copy of the widget in Omarchy's user plugin directory:

   ```sh
   plugin_dir="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/io.github.noflairos.focus-ratio"
   mkdir -p "$plugin_dir"
   install -m 0644 manifest.json BarWidget.qml Panel.qml "$plugin_dir/"
   omarchy plugin enable io.github.noflairos.focus-ratio
   omarchy restart shell
   ```

   `omarchy plugin add` accepts a Git URL, so the manual copy is the local
   development path. Repeat the copy after editing the checkout. Restarting
   the shell also replaces any old panel instance that is still open.

3. **Optional, for site tracking:** in Chromium, open `chrome://extensions`,
   enable Developer mode, and load the installed extension folder at
   `~/.local/share/focus-ratio/browser`. Copy its extension ID and register
   the native host:

   ```sh
   ./scripts/install-browser-host.sh EXTENSION_ID
   ```

4. Restart Chromium if you installed the extension. The widget tracks desktop
   apps without it, including Chromium as one app; the extension adds
   active-site tracking when a browser window title matches the active tab.
   Use the panel to classify targets and adjust consumption quotas. New targets appear in
   Review; the initial consumption quota is 10 minutes/hour.

To remove the widget from the bar, run
`omarchy plugin disable io.github.noflairos.focus-ratio`, then remove its
directory from `${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/`. Remove the
helper and browser host with `./scripts/uninstall-local.sh`.

The browser bridge needs Chromium's `tabs` and `nativeMessaging`
permissions to read active tab domains, identify normal/minimized windows, and
communicate with the local service. A content script reads only the declared service name (`application-name` or
`og:site_name`) from page metadata. It does not read the page body. These names
are cached locally; sites without metadata use their complete domain. No
hardcoded service-name list is used. Reload the extension and existing tabs
after an update that adds the content script. The
Marketplace plugin runs as the user inside `omarchy-shell`; the helper is
separate so window monitoring does not block or pollute the shell process.

The schedule uses the system's local time and can be changed directly in Manage.
Uninstalling the helper leaves user settings and history in place.

## Development

The plugin is a regular Omarchy `bar-widget`; it does not start a second
Quickshell process. Monitoring and enforcement run in a separate user-level
service so the shell widget remains lightweight. The service and browser bridge
require no root privileges and document their permissions.

Checks (Python 3, Node.js, QtTest and Omarchy required):

```sh
./scripts/check.sh
```

The plugin should be installed from a user-owned checkout for local testing.

The installer and widget honor `XDG_DATA_HOME`, `XDG_CONFIG_HOME`, and
`XDG_STATE_HOME` when those locations are set. The user service is generated
with the matching install, config, and state paths so its filesystem sandbox
can write only to the Focus data directories.

## Manage and manual groups

Manage has collapsed sections for Tracking schedule, Groups, Apps & sites,
Diagnostics and Data export. Save two entries in Review first, then choose
a source and destination under Groups. The destination keeps
its category, quota and limit action. Existing usage is added together; past
overlap cannot be reconstructed and merged history cannot be separated later.
All members subsequently share one counter, counting simultaneous use once.

Pause, idle/lock and out-of-schedule periods suspend tracking and enforcement.
Only active site tabs matched to a visible desktop window may be closed.
Ambiguous titles are skipped instead of assigning activity to an arbitrary window.

Chromium and Google Chrome on Linux are supported. After installing the
extension, register its ID with `scripts/install-browser-host.sh EXTENSION_ID`;
this installs the native-host registration for both browsers. The extension
popup checks the helper connection and shows its ID for setup.

See [PRIVACY.md](PRIVACY.md) for data handling and deletion. Public store
submission still requires a public repository, a hosted privacy-policy URL,
store screenshots and review of the complete installation on a clean machine.

Browser enforcement checks: `node tests/test_browser.js`.

Apps & sites supports name/domain/member search and category filters. Groups
show expandable members with a Detach action. Detached entries inherit the
group settings and begin independent tracking; existing merged usage stays
with the remaining group, including when its main entry is detached. Explicit
detachment is remembered so automatic web-app matching does not recreate it.
Diagnostics reports connection status even while collapsed.

## Everyday controls

- Pause offers 15 minutes, one hour, until local midnight tomorrow, or until
  resumed. Pause state survives helper restarts.
- Apps & sites includes Warn before limit (enabled by default). It sends
  one desktop notification per service/hour while the helper is running, up to
  two minutes before the limit, or half the quota for shorter limits.
- History starts with a rolling seven-day summary, compared with the previous
  seven days. Recorded-day counts are shown; missing periods are not treated
  as recorded zero usage. Category activity can exceed screen time because
  distinct services can be visible together.
- Groups suggests saved entries with matching names, for manual review only.
  Dismissed suggestions stay hidden. Detachment prevents automatic linking,
  while manual suggestions remain available.
- Data export saves history to CSV and backs up settings as JSON under
  `~/.local/state/focus-ratio/exports/` (or the XDG state equivalent). The panel
  opens the export folder after completion. Clearing history requires a second
  confirmation and resets current-hour usage; settings and exports remain.

To restore settings on another Omarchy machine, install the helper, stop it
with `systemctl --user stop focus-ratio.service`, copy the backup JSON to
`~/.config/focus-ratio/config.json` (or its XDG equivalent), then restart the
service. The backup does not contain usage history. Browser registration is
performed separately with the extension ID.

UI integration check: `python3 tests/check_panel.py` (QtTest required). This
uses shell fixtures; final visual checks should also run in Omarchy itself.

## Release preparation

Public name: **Focus**. The existing `focus-ratio` identifiers and storage paths
are retained for compatibility. See [release/README.md](release/README.md) for
local packaging and the store submission drafts. Build archives with
`python3 scripts/build-release.py`; this does not publish or install anything.
