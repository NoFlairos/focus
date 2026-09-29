# Isolated validation — 2026-09-29

## Passed

- 40 Python tests, browser enforcement tests, Qt panel integration and Omarchy manifest validation.
- The real installation script copied helper, extension, PNG icons and user service into empty XDG directories.
- systemd-analyze verify --user accepted the generated service unit.
- A real helper daemon started with an empty SQLite database and served its Unix socket.
- Chromium 152 loaded the actual unpacked extension in a fresh profile.
- The real native-host registration script registered that extension ID.
- The extension's nativeMessaging API connected through the installed host to the helper.
- The actual extension UI reported Connected; after stopping the helper, Refresh reported Not connected.
- The installed CLI disabled the warning and the daemon persisted/reported it.
- No desktop apps or personal browser activity entered the isolated history.
- Uninstall removed helper files, unit and both browser registrations while retaining history.
- Two unaltered 640×400 PNG captures were reviewed for private data.

## Isolation and exact scope

Reproduce using ./scripts/check-isolated.sh (bubblewrap, Chromium, Node.js,
Python and systemd-analyze required). Results are written to dist/isolated-check.
The container has separate network/PID namespaces and temporary XDG directories.
Project files and OS files are read-only; the host home, desktop sockets and
session bus are not mounted. Chromium's inner sandbox is disabled only for this
outer-container test. A separate browser profile is created and deleted.

The installer and uninstaller run unchanged. Their systemctl calls are logged by
a test substitute to avoid reaching the real session manager. The helper itself
is real and is launched directly. Unit-file verification is real; activation by
systemd, graphical-session lifecycle and enforcement of systemd sandbox options
are NOT proven by this test.

Browser captures show the extension's own status.html, opened from its loaded
chrome-extension URL in a 640×400 viewport with dark color preference. No labels
or connection results were replaced. The setup disclosure was collapsed through
its real click handler for the offline capture. These are extension captures,
not captures of the Omarchy desktop panel.

## Remaining before publication

- Boot a fresh Omarchy installation and validate systemd session activation,
  restart behavior, installed file permissions and desktop tracking end to end.
- Check real desktop visibility, pause/idle/lock, schedule and limit enforcement
  together. Automated accounting/browser tests already cover these separately.
- Complete the full-session behavioral check; user-supplied panel captures are now available.
- Validate the published Chrome build using its store-assigned extension ID.

A headless Hyprland session was attempted for panel capture but its graphics
backend could not start in this environment; no /dev/dri device is available.
No screenshot using substitute QML components is supplied as a store image.

Nothing was uploaded, no public repository was created, and the user's running
Focus installation, browser profile, settings and history were left untouched.

User-supplied panel and bar screenshots were subsequently cropped without
changing their contents. They document the existing installation, not a completed
clean-machine test. See CAPTURES.md for selection and limitations.
