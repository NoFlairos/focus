# Chrome Web Store draft

**Name:** Focus — Site Tracker
**Category:** Productivity · **Language:** English
**Summary:** Stay focused and keep distracting sites in check. A local companion for Focus on Omarchy Linux.

## Description

Stay focused. Make time for what matters.

Focus helps you understand where your screen time goes and keep distractions in
check. Separate productive work from consumption and set limits that fit your routine.

• Track your daily screen time.
• Classify apps and sites as Productive, Neutral or Consumption.
• Set hourly limits for distracting services.
• Share one limit across an app and its website.
• Choose tracking hours, pause when needed, and review your week.

This extension adds website tracking to Focus for Omarchy Linux. It requires the
Focus desktop plugin and local helper, and supports Chromium and Google Chrome.

Only active tabs matched to visible windows count. Choose a notification, keep
the site open, or close its active tab when the limit is reached.

Your activity stays on your computer. No account, analytics or remote tracking server.

Get started: https://github.com/NoFlairos/focus#install

## Privacy declarations

**Single purpose:** active-site tracking and limit enforcement for local Focus.

| Access | Reason |
| --- | --- |
| tabs | Match active domains, titles and tab/window IDs to visible desktop windows; close eligible tabs at their limit. |
| nativeMessaging | Exchange site metadata and limit decisions with the local helper. |
| HTTP/HTTPS content scripts | Read declared application names and manifest references for labels and grouping; manifests are not fetched. |

Titles and matching data are transient. Domains, declared site names, usage and
settings may be stored locally. No page body, form fields, passwords or cookies
are read. No remote code, sale, advertising, credit decisions or third-party
sharing. Confirm dashboard declarations against its definitions before submission.

## Files and links

- ZIP: `dist/focus-chrome-0.5.0.zip`
- Icon: `extensions/chromium/icons/128.png`
- Promo: `release/assets/promo-440x280.png`
- Screenshots: `release/assets/extension-connected.png` and `extension-offline.png`
- Homepage: https://github.com/NoFlairos/focus
- Support: https://github.com/NoFlairos/focus/issues
- Privacy: https://noflairos.github.io/focus/privacy.html

Remaining: publisher/contact details, account declarations, countries and visibility.
Choose deferred publishing. [Reviewer instructions](REVIEWER.md).

References checked 2026-09-29: [images](https://developer.chrome.com/docs/webstore/images),
[privacy fields](https://developer.chrome.com/docs/webstore/cws-dashboard-privacy),
[submission](https://developer.chrome.com/docs/webstore/publish).
