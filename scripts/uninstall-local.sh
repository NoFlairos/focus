#!/usr/bin/env bash
set -euo pipefail

install_dir="${XDG_DATA_HOME:-$HOME/.local/share}/focus-ratio"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
host_file="${XDG_CONFIG_HOME:-$HOME/.config}/chromium/NativeMessagingHosts/io.github.noflairos.focus_ratio.json"

systemctl --user disable --now focus-ratio.service 2>/dev/null || true
rm -f "$unit_dir/focus-ratio.service" "$host_file"
rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/google-chrome/NativeMessagingHosts/io.github.noflairos.focus_ratio.json"
systemctl --user daemon-reload
rm -rf "$install_dir"
echo "Focus service removed. Settings and history were kept."
