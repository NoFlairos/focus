# Focus 0.5.0

- Browser connection status in the bar and Diagnostics, with a launch grace period.
- Automatic Smart/Group domain linking and migration of existing rules.
- Exclude classified entries; hide exclusions together or individually.
- Track again restores entries immediately without reopening their sites.
- One domain selector per group and arrows to jump to either end of long lists.
- Local declared site identity from open tabs improves Smart grouping; background
  tabs still do not count or become closing targets.

The installer now requires libpsl. Existing settings and classified history are
preserved. Grouping combines historical counters, which cannot later be split.
After installing, reload the unpacked extension and existing tabs for new metadata
handling. The previous Chrome Web Store submission is unchanged.

Validation: 73 Python tests, browser enforcement, Qt integration and an isolated
real Chromium/helper test. Fresh Omarchy session checks remain outstanding; see
[validation](VALIDATION.md).
