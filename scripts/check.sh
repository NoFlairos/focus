#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

for script in scripts/*.sh tests/*.sh; do
  bash -n "$script"
done
for script in extensions/chromium/*.js tests/*.js tests/*.mjs; do
  node --check "$script"
done
python3 - <<'PY'
import ast
import json
from pathlib import Path

for directory in ("agent", "tests", "scripts"):
    for path in Path(directory).glob("*.py"):
        ast.parse(path.read_text(), filename=str(path))
assert list(Path(".").glob("*/manifest.json")) == [], "Only the root manifest may be at marketplace discovery depth"
for path in (Path("manifest.json"), Path("extensions/chromium/manifest.json")):
    json.loads(path.read_text())
PY
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q
node tests/test_browser.js
python3 tests/check_panel.py
omarchy plugin validate "$repo_dir"
printf 'All checks passed.\n'
