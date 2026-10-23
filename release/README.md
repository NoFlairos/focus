# Publication

| Channel | Status |
| --- | --- |
| [GitHub](https://github.com/NoFlairos/focus) | Source and releases; this repository is the plugin source. |
| [Omarchy plugin catalog](https://omarchyplugins.com/plugin.html?id=io.github.noflairos.focus-ratio) | Listed; updates go through a *Verify* issue for the new commit. |
| [Chrome Web Store](https://chromewebstore.google.com/detail/dmeieacelhalokmjoijllpieglfjojjo) | Published, 0.5.1 (current extension build). |

| File | Purpose |
| --- | --- |
| [CHROME-STORE.md](CHROME-STORE.md) | Listing text and permission declarations |
| [OMARCHY-STORE.md](OMARCHY-STORE.md) | Catalog entry |
| [REVIEWER.md](REVIEWER.md) | Reviewer setup and test steps |
| [VALIDATION.md](VALIDATION.md) | Tests run and remaining checks |
| [CAPTURES.md](CAPTURES.md) | Image sources |

Build: `./scripts/check.sh`, then `python3 scripts/build-release.py`. Archives and
SHA256SUMS go to `dist/`; installed user data is never included and nothing is uploaded.
Artwork sources are in `assets/`, store images in `release/assets/`, the privacy page in `site/`.
