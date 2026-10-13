# Changelog

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
