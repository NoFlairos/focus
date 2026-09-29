# Focus 0.4.0 — local release preparation

This folder is a publication draft. Nothing has been uploaded or submitted.

- CHROME-STORE.md: listing, permission explanations and outstanding account fields.
- OMARCHY-STORE.md: catalog submission and mandatory helper disclosure.
- REVIEWER.md: installation and behavior verification instructions.
- assets/: store promotional image, extension screenshots and user-supplied panel/bar crops.
- VALIDATION.md: passed isolated checks and remaining full-session verification.
- ../site/privacy.html: standalone privacy page, ready for later hosting.
- ../assets/: editable original SVG artwork; MIT licensed with the project.

Build and verify:

```sh
./scripts/check.sh
python3 scripts/build-release.py
```

The deterministic ZIPs contain only allowlisted project files. They never package
installed settings, activity history, native-host registrations or credentials.
SHA256SUMS records the resulting archives. No Git initialization, remote upload,
service restart or installation is performed by the build.

Public name: Focus. Existing plugin ID, native-host name, paths and systemd unit
retain focus-ratio to preserve compatibility. Plugin and extension versions: 0.4.0.

Before submission:
- Complete the separately approved clean-install test.
- Extension screenshots and approved panel/bar crops are prepared (see CAPTURES.md).
- Confirm final artwork and listing copy.
- Supply the public source, support and hosted privacy URLs.
- Confirm publisher account declarations and distribution choices.
- Register the store-assigned extension ID when testing the store build.

No store approval or name availability is assumed.

Artwork can be regenerated with librsvg:

```sh
for size in 16 32 48 128; do
  rsvg-convert -w "$size" -h "$size" assets/focus.svg -o "browser/icons/$size.png"
done
rsvg-convert assets/promo.svg -o release/assets/promo-440x280.png
```
