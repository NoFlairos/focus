# Publication

[Source](https://github.com/NoFlairos/focus) ·
[0.4.0 release](https://github.com/NoFlairos/focus/releases/tag/v0.4.0) ·
[Privacy](https://noflairos.github.io/focus/privacy.html)

Store submissions require separate approval.

| File | Purpose |
| --- | --- |
| [CHROME-STORE.md](CHROME-STORE.md) | Chrome listing and permission declarations |
| [OMARCHY-STORE.md](OMARCHY-STORE.md) | Omarchy submission |
| [REVIEWER.md](REVIEWER.md) | Reviewer setup |
| [VALIDATION.md](VALIDATION.md) | Tests and remaining checks |
| [CAPTURES.md](CAPTURES.md) | Images and edits |

Build: `./scripts/check.sh`, then `python3 scripts/build-release.py`.
Archives and SHA256SUMS go to `dist/`; installed user data is never included.
Artwork sources are in `assets/`, store images in `release/assets/`, and the
privacy page in `site/`. Nothing is uploaded by the build.

Before submission: finish the fresh-session checks, confirm publisher/contact
and distribution settings, and test the store-assigned extension ID.
