# Changelog

## 0.9.1 — 2026-10-23 · extension 0.5.1

- **Site names stay minimal:** names and identities are kept only for sites on screen
  while tracking, or already in Focus. Background tabs and paused browsing leave nothing.
  Automatic subdomain groups are limited to the 500 most recent; manual merges stay.
- **Bounded everywhere:** the extension caps what a page can report and sends it only
  with the one-second snapshot; the bridge answers bad messages instead of stopping;
  the bar shows at most 8 chips, the panel 300 entries, the agent 60 visible entries.
- **Sturdier helper:** one instance at a time, socket timeouts, damaged settings
  repaired key by key, and a failing tick no longer stops tracking.
- **Installer:** empty or relative XDG folders are ignored, unsafe folder names are
  refused for the systemd unit, and the service and bridge use the same folders.
- *Open export folder* only opens the exact export folder.

## 0.9.0 — 2026-10-23

- App and site names never appear in a process command line, which other users
  can read: notifications are sent over D-Bus instead of `notify-send` (clicking
  still grants 5 more minutes), and the panel passes commands to the helper on stdin.

## 0.8.9 — 2026-10-22

- **About 3× lighter:** a closed panel no longer rebuilds its lists on every
  update, and the agent resolves links and names once per tick instead of per
  entry. Measured with one visible app: ~5.6 % of a core → ~1.9 % (shell + agent).

## 0.8.8 — 2026-10-22

- Settings, history and exports are private: files are created owner-only from
  the start, the service runs with `UMask=0077`, and existing folders and files
  are tightened to 0700/0600 on start and by the installer.

## 0.8.7 — 2026-10-21

- Every text and tooltip is rendered as plain text, so app and site names can
  never be read as markup; names in notification bodies are escaped.

## 0.8.6 — 2026-10-17

- *Merge into…* is a plain list without a search field, so no part of the panel
  reads the clipboard. Entries show their address when it differs from the name.
- App names from Hyprland are capped at 120 characters, like site names.
- *Open export folder* only opens Focus's own export folder.

## 0.8.5 — 2026-10-15

- No native text field remains, so the panel never reads the clipboard:
  schedule times use −/+ buttons (15 minutes, the wheel works too) and Search
  reads typed keys directly. Pasting into Search is no longer possible.

## 0.8.4 — 2026-10-14

- The schedule time and app search fields only exist while shown, so a hidden
  panel no longer reads the clipboard when it changes.

## 0.8.3 — 2026-10-14

- The bar no longer shows a "+5 min" chip after a limit: the notification and the
  *Limit reached* block in Now are enough.

## 0.8.2 — 2026-10-14

- **5 more minutes is reachable:** Omarchy notifications show no action buttons, so
  clicking the limit notification itself now grants the extension.

## 0.8.1 — 2026-10-14

- **Lighter on the system:** the live status is kept in memory instead of being
  rewritten on disk every second; usage is committed every 30 s and on stop
  (a crash loses at most 30 s); Hyprland is queried over its socket instead of
  spawning `hyprctl`; lock/idle state is polled every 5 s.
- The installer adds the in-memory runtime directory to the user service.

## 0.8.0 — 2026-10-13

- **Limits:** per hour or per day, a daily Consumption budget, and *5 more minutes*
  once per period — from a notification that stays until answered, or from Now for
  two minutes after a limit is reached.
- **Focus sessions** of 25, 50 or 90 minutes block all Consumption, even outside the schedule.
- **History:** click a day for its top entries; *Worth a limit* proposes a daily limit
  for heavily used entries without one; optional weekly summary notification.
- **Days start at 04:00** by default, so late nights count toward the evening before.
- **Review** only lists entries used 10+ minutes over 7 days; pending subdomains share one card.
- **Smart grouping** merges a site's subdomains unless they declare their own web app,
  application name or category. Site names drop parenthesised asides.
- **Panel:** entry details under *More*, collapsed exclusions, autosaved schedule,
  *Connection & data* section, Omarchy toggles and steppers, Chromium-calibrated scrolling.
- **Bar:** the Focus mark replaces the text when no tracked app is visible.
- **Reliability:** commands run in order; state is written only when it changes;
  configuration lists are pruned daily.

The browser extension is unchanged since 0.5.0.

## 0.5.0 — 2026-10-02

- Browser connection status in the bar and Diagnostics.
- Automatic Smart/Group domain linking; Track again restores entries immediately.
- Site identity from open background tabs improves grouping; background tabs never count.
- The installer requires libpsl.

## 0.4.0 — 2026-09-29

First public release: local screen time, categories, hourly limits, schedules, pauses,
shared counters, seven-day history, exports and the Chromium/Chrome extension.
