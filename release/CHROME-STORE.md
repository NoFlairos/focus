# Chrome Web Store — local draft

## Listing

Name: Focus — Site Tracker

Summary: Track active sites with Focus for Omarchy on Linux. Requires the local Focus helper.

Category: Productivity
Language: English

Description:

Focus adds website tracking to Focus for Omarchy on Linux.

See which sites are active in visible browser windows, classify them as Productive,
Neutral or Consumption, and manage hourly limits in the Focus desktop panel.
Link an app and a website to share a counter. Pause tracking or set tracking hours.

The extension requires Omarchy, the Focus desktop plugin and its local helper.
It is a companion extension, not a standalone tracker. Install the helper and
register this extension's ID using the setup instructions in the project README.
Chromium and Google Chrome on Linux are supported.

Only active tabs matched to visible browser windows contribute site activity.
Background tabs do not count. If you choose the Close action, tabs that reach
an hourly consumption limit are closed while tracking is active.

Tracking data stays on your computer. No account, analytics or remote tracking
server is used. The toolbar popup shows the local connection status.

## Privacy field drafts

Single purpose:
Provide active-site tracking and hourly site-limit enforcement for the local
Focus application on Omarchy Linux.

Permission: tabs
Read active tab domains, titles, IDs and window state to match browser tabs
with visible desktop windows. Close only matching active tabs whose configured
hourly limit is reached. Titles are matched in memory, not stored in history.

Permission: nativeMessaging
Exchange active-site metadata and limit decisions with the user's separately
installed local Focus helper. No remote server is involved.

Content-script access: HTTP and HTTPS
Read only application-name or og:site_name metadata for site labels. Scripts do
not read the page body, form fields, passwords or cookies.

Remote code: No. All executable extension code is included in the ZIP.

Data handling for dashboard review:
- Browsing activity: active domains, titles, tab/window IDs and window state.
- Website metadata: declared service names.
- Domains, site names, classifications and usage totals can be stored by the local helper.
- Titles and window matching data are transient.
- No transmission to the developer or third parties; local native messaging only.
- No sale, advertising, credit decisions or unrelated use of data.

These are factual drafting notes, not preselected dashboard declarations.
Review the dashboard's definitions before confirming its data-use certifications.
Do not describe this as "no browsing data is handled".

## Assets and remaining fields

- ZIP: dist/focus-chrome-0.4.0.zip
- Icon: browser/icons/128.png
- Small promotional image: release/assets/promo-440x280.png
- Actual extension screenshots (640×400): release/assets/extension-connected.png and extension-offline.png.
- Desktop panel/bar crops: available for project documentation; see CAPTURES.md.
  Their native sizes are not Chrome Store screenshot dimensions.
- Homepage: https://github.com/NoFlairos/focus
- Support: https://github.com/NoFlairos/focus/issues
- Privacy: https://noflairos.github.io/focus/privacy.html
- Developer identity, contact and account declarations: supplied by the publisher.
- Visibility and countries: confirm before submission.
- Use deferred publishing so review approval does not automatically publish.

Sources checked 2026-09-29:
- https://developer.chrome.com/docs/webstore/prepare
- https://developer.chrome.com/docs/webstore/images
- https://developer.chrome.com/docs/webstore/cws-dashboard-privacy
- https://developer.chrome.com/docs/webstore/publish
