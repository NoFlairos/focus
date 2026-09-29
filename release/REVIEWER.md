# Reviewer setup and verification

Platform: Omarchy Linux with Hyprland, Quickshell, Python 3, systemd user services
and Chromium or Google Chrome. No product login or paid subscription is needed.
The extension cannot be tested as a standalone tracker on another OS.

1. Obtain https://github.com/NoFlairos/focus/releases/tag/v0.4.0.
2. Run ./scripts/install-local.sh, then follow README.md to install the Omarchy widget.
3. Load browser/ unpacked, or install the review build supplied by the store.
4. Copy the actual extension ID from its popup or chrome://extensions.
5. Run ./scripts/install-browser-host.sh EXTENSION_ID and restart the browser.
   The store-assigned ID may differ from an unpacked build; register the ID in use.
6. Open the popup. Refresh should show Connected when the helper is running.
7. In Manage → Tracking schedule, select today and All day, then Save.
8. Open a harmless test site in a visible browser window. Classify it in Review.
   Confirm that an inactive background tab does not accumulate site time.
9. On a disposable test tab, choose Consumption and a one-minute hourly limit.
   With Close selected, confirm the matching active tab closes at the limit.
   Repeat with Notify / keep-open actions as named in the panel, then pause and
   confirm enforcement stops. Avoid tabs containing unsaved work for this test.
10. Verify manual groups, detach, warning On/Off, history and data export.
11. Stop the helper and check that the popup reports it unavailable. Restart it.
12. Follow README.md uninstall instructions. Settings/history are intentionally
    retained; PRIVACY.md explains full local data deletion.

Use synthetic activity in an isolated environment for store screenshots. Capture
actual UI, without personal browsing domains, tab titles, extension IDs or paths.
Do not present an illustrative mockup as a working-product screenshot.

Status: isolated installation and native-browser checks passed; see VALIDATION.md.
Full graphical-session execution on a fresh Omarchy machine remains outstanding.
