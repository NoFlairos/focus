#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
install_dir="${XDG_DATA_HOME:-$HOME/.local/share}/focus-ratio"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/focus-ratio"
state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/focus-ratio"

mkdir -p "$install_dir" "$install_dir/browser" "$install_dir/browser/icons" "$unit_dir" "$config_dir" "$state_dir"
install -m 0755 "$repo_dir/agent/focus_ratio_agent.py" "$install_dir/focus_ratio_agent.py"
install -m 0644 "$repo_dir"/browser/*.json "$repo_dir"/browser/*.js "$repo_dir"/browser/*.html "$install_dir/browser/"
install -m 0644 "$repo_dir"/browser/icons/*.png "$install_dir/browser/icons/"
cat > "$unit_dir/focus-ratio.service" <<EOF
[Unit]
Description=Focus local application and site tracker
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=simple
ExecStart="$install_dir/focus_ratio_agent.py" --daemon
Restart=on-failure
RestartSec=2
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths="$config_dir" "$state_dir"

[Install]
WantedBy=graphical-session.target
EOF

systemctl --user daemon-reload
systemctl --user reenable focus-ratio.service
systemctl --user restart focus-ratio.service

printf 'Focus service installed and started.\n'
printf 'Load this extension folder in Chromium: %s\n' "$install_dir/browser"
printf 'Copy its extension ID, then run: %s/scripts/install-browser-host.sh EXTENSION_ID\n' "$repo_dir"
