# Validation — 2026-11-04 (0.9.5)

**Passed:** 103 Python tests, browser enforcement tests, 16 Qt panel tests,
Omarchy manifest validation and systemd unit-file validation.

An isolated Chromium 155 profile loaded the real extension and connected to the
installed native host and helper. An active tab closed at its limit while a
background tab stayed open; Smart grouping joined two pages declaring the same
application; connection loss, installation and removal passed.

Limits (hour, day, budget, focus session, 5 more minutes), day-start shifting,
limit suggestions, Review threshold and subdomain grouping have regression coverage.
Tests never show real notifications or close real windows.

Used daily on Omarchy since 0.4: panel, bar mark and scrolling were checked on a
1.57× display. Reproduce the isolated run with `./scripts/check-isolated.sh`
(bubblewrap, temporary profiles and XDG folders, no personal desktop or session bus).

**Not yet covered:** a fresh Omarchy installation from the catalog. The Chrome Web
Store now serves extension 0.5.1, the build tested above.
