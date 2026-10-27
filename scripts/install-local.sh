#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_dir/scripts/paths.sh"

# Show exactly which code becomes a service, so it can be compared with the verified commit.
if commit="$(git -C "$repo_dir" rev-parse --verify HEAD 2>/dev/null)"; then
  if git -C "$repo_dir" symbolic-ref -q HEAD >/dev/null; then
    printf 'Note: installing a branch, not a pinned commit. See README: git checkout --detach COMMIT\n' >&2
  fi
  if [[ -n "$(git -C "$repo_dir" status --porcelain --untracked-files=no)" ]]; then
    printf 'Note: this checkout has local changes.\n' >&2
  fi
  printf 'Installing Focus from commit %s\n' "$commit"
fi
unit_dir="$config_home/systemd/user"
config_dir="$config_home/focus-ratio"
state_dir="$state_home/focus-ratio"
# These paths are written into a systemd unit: refuse anything systemd would reinterpret.
unsafe='[%"\$[:cntrl:]]'
for path in "$install_dir" "$config_dir" "$state_dir"; do
  if [[ "$path" =~ $unsafe ]]; then
    printf 'Focus cannot use this folder in a systemd unit: %q\n' "$path" >&2
    exit 1
  fi
done

python3 -c 'import ctypes; ctypes.CDLL("libpsl.so.5")' || { printf 'Focus requires libpsl. Install the libpsl package first.\n' >&2; exit 1; }
python3 -c 'import gi; gi.require_version("Gio", "2.0"); from gi.repository import Gio' 2>/dev/null \
  || { printf 'Focus requires python-gobject for notifications. Install the python-gobject package first.\n' >&2; exit 1; }

mkdir -p "$install_dir" "$install_dir/browser" "$install_dir/browser/icons" "$unit_dir"
# Settings and history are private to the user, including on existing installs.
mkdir -p -m 0700 "$config_dir" "$state_dir"
chmod 0700 "$config_dir" "$state_dir"
install -m 0755 "$repo_dir/agent/focus_ratio_agent.py" "$install_dir/focus_ratio_agent.py"
install -m 0644 "$repo_dir"/extensions/chromium/*.json "$repo_dir"/extensions/chromium/*.js "$repo_dir"/extensions/chromium/*.html "$install_dir/browser/"
install -m 0644 "$repo_dir"/extensions/chromium/icons/*.png "$install_dir/browser/icons/"
cat > "$unit_dir/focus-ratio.service" <<EOF
[Unit]
Description=Focus local application and site tracker
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=simple
ExecStart="$install_dir/focus_ratio_agent.py" --daemon
# The helper must use the folders created above, whatever the systemd environment says.
Environment="XDG_CONFIG_HOME=$config_home" "XDG_STATE_HOME=$state_home" "XDG_DATA_HOME=$data_home"
Restart=on-failure
RestartSec=2
NoNewPrivileges=true
UMask=0077
# No network: Hyprland, D-Bus, the session and the browser bridge are all local sockets.
RestrictAddressFamilies=AF_UNIX
LockPersonality=true
RestrictRealtime=true
RestrictSUIDSGID=true
SystemCallArchitectures=native
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths="$config_dir" "$state_dir"
# Live state for the bar widget lives in RAM: \$XDG_RUNTIME_DIR/focus-ratio.
RuntimeDirectory=focus-ratio
RuntimeDirectoryMode=0700

[Install]
WantedBy=graphical-session.target
EOF

"$repo_dir/scripts/install-browser-host.sh"

systemctl --user daemon-reload
systemctl --user reenable focus-ratio.service
systemctl --user restart focus-ratio.service

printf 'Focus service installed and started.\n'
printf 'Load this extension folder in Chromium: %s\n' "$install_dir/browser"
printf 'Copy its extension ID, then run: %s/scripts/install-browser-host.sh EXTENSION_ID\n' "$repo_dir"
