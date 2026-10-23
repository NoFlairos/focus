#!/usr/bin/env bash
set -euo pipefail

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/paths.sh"
unit_dir="$config_home/systemd/user"
host_file="$config_home/chromium/NativeMessagingHosts/io.github.noflairos.focus_ratio.json"

systemctl --user disable --now focus-ratio.service 2>/dev/null || true
rm -f "$unit_dir/focus-ratio.service" "$host_file"
rm -f "$config_home/google-chrome/NativeMessagingHosts/io.github.noflairos.focus_ratio.json"
systemctl --user daemon-reload
rm -rf "$install_dir"
echo "Focus service removed. Settings and history were kept."
