# Validation — 2026-10-02

**Passed:** 73 Python tests, browser enforcement tests, Qt panel integration,
Omarchy manifest validation and systemd unit-file validation.

An isolated Chromium 152 profile loaded the real extension and connected to the
installed native host and helper. Connection loss, warning persistence and
installation/removal passed; uninstall retained history as documented.
Smart/Group linking, rule migration, exclusions, immediate Track again recovery,
privacy controls and both scroll shortcuts have regression coverage.

Reproduce with `./scripts/check-isolated.sh`. Bubblewrap isolates network/processes
and uses temporary profiles and XDG folders, without the personal desktop or
session bus. Chromium's inner sandbox is disabled only inside this outer sandbox.
The helper runs directly; systemctl calls are recorded by a test substitute.
Qt integration uses shell fixtures.

**Still required:** full startup/restart and systemd sandbox behavior in a fresh
Omarchy session, combined desktop tracking/enforcement checks, and testing with
the Chrome Store extension ID. A headless panel session could not start here
because the graphics backend was unavailable.

[Captures](CAPTURES.md) document the extension test and the user's existing desktop;
they do not establish that fresh-machine testing is complete.
