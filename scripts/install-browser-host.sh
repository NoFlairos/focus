#!/usr/bin/env bash
set -euo pipefail

extension_id="${1:-dmeieacelhalokmjoijllpieglfjojjo}"
if [[ $# -gt 1 || ! "$extension_id" =~ ^[a-p]{32}$ ]]; then
  echo "Usage: $0 [CHROMIUM_EXTENSION_ID]" >&2
  echo "Omit the ID for the Chrome Web Store extension." >&2
  exit 2
fi

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
install_dir="${XDG_DATA_HOME:-$HOME/.local/share}/focus-ratio"
if [[ ! -x "$install_dir/focus_ratio_agent.py" ]]; then
  echo "Install the helper first: $repo_dir/scripts/install-local.sh" >&2
  exit 1
fi
install -m 0755 "$repo_dir/scripts/native-host.sh" "$install_dir/native-host.sh"
for browser in chromium google-chrome; do
  host_dir="${XDG_CONFIG_HOME:-$HOME/.config}/$browser/NativeMessagingHosts"
  host_file="$host_dir/io.github.noflairos.focus_ratio.json"
  mkdir -p "$host_dir"
  python3 - "$host_file" "$install_dir/native-host.sh" "$extension_id" <<'PY'
import json
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
origins = {f"chrome-extension://{sys.argv[3]}/",
           "chrome-extension://dmeieacelhalokmjoijllpieglfjojjo/"}
if path.exists():
    previous = json.loads(path.read_text())
    origins.update(origin for origin in previous.get("allowed_origins", [])
                   if isinstance(origin, str) and re.fullmatch(r"chrome-extension://[a-p]{32}/", origin))
path.write_text(json.dumps({
    "name": "io.github.noflairos.focus_ratio",
    "description": "Local bridge for Focus",
    "path": sys.argv[2],
    "type": "stdio",
    "allowed_origins": sorted(origins),
}, indent=2) + "\n", encoding="utf-8")
PY
  chmod 0644 "$host_file"
done
printf 'Registered Focus native messaging host for Chromium and Google Chrome. Restart your browser.\n'
