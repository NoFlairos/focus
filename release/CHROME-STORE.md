# Chrome Web Store draft

**Name:** Focus — Site Tracker
**Category:** Productivity · **Language:** English
**Summary:** Track active sites with Focus for Omarchy on Linux. Requires the local Focus helper.

## Description

Track active websites in Focus for Omarchy Linux. Classify sites, set hourly
limits and share a counter with related apps. Manage schedules and pauses in
the desktop panel; check the helper connection in the extension popup.

Requires the Focus desktop plugin and local helper. Supports Chromium and
Google Chrome on Linux. Only active tabs matched to visible windows count.
Choosing Close closes those tabs when their limit is reached.

Data stays on your computer. No account, analytics or remote tracking server.

## Privacy declarations

**Single purpose:** active-site tracking and limit enforcement for local Focus.

| Access | Reason |
| --- | --- |
| tabs | Match active domains, titles and tab/window IDs to visible desktop windows; close eligible tabs at their limit. |
| nativeMessaging | Exchange site metadata and limit decisions with the local helper. |
| HTTP/HTTPS content scripts | Read application-name or og:site_name metadata for labels. |

Titles and matching data are transient. Domains, declared site names, usage and
settings may be stored locally. No page body, form fields, passwords or cookies
are read. No remote code, sale, advertising, credit decisions or third-party
sharing. Confirm dashboard declarations against its definitions before submission.

## Files and links

- ZIP: `dist/focus-chrome-0.4.0.zip`
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
