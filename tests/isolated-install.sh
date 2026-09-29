#!/usr/bin/env bash
set -euo pipefail
mkdir -p /test/bin /test/data /test/config /test/state /test/runtime
chmod 700 /test/runtime
cat > /test/bin/systemctl <<'SH'
#!/bin/sh
printf '%s\n' "$*" >> /test/systemctl-requests.log
SH
chmod +x /test/bin/systemctl
export PATH="/test/bin:/usr/bin"
export XDG_DATA_HOME=/test/data XDG_CONFIG_HOME=/test/config XDG_STATE_HOME=/test/state XDG_RUNTIME_DIR=/test/runtime
unset DBUS_SESSION_BUS_ADDRESS HYPRLAND_INSTANCE_SIGNATURE WAYLAND_DISPLAY DISPLAY XDG_SESSION_ID
bash /project/scripts/install-local.sh
SYSTEMD_UNIT_PATH=/usr/lib/systemd/user:/test/config/systemd/user systemd-analyze verify --user /test/config/systemd/user/focus-ratio.service > /test/unit-check.log 2>&1 || { cat /test/unit-check.log; exit 1; }
python3 /test/data/focus-ratio/focus_ratio_agent.py --daemon > /test/helper.log 2>&1 &
helper_pid=$!
trap 'kill "$helper_pid" 2>/dev/null || true' EXIT
printf "%s" "$helper_pid" > /test/helper.pid
node /project/tests/isolated-browser.mjs
kill "$helper_pid" 2>/dev/null || true
wait "$helper_pid" || true
bash /project/scripts/uninstall-local.sh
test ! -e /test/data/focus-ratio
test ! -e /test/config/systemd/user/focus-ratio.service
test ! -e /test/config/chromium/NativeMessagingHosts/io.github.noflairos.focus_ratio.json
test ! -e /test/config/google-chrome/NativeMessagingHosts/io.github.noflairos.focus_ratio.json
test -f /test/state/focus-ratio/history.sqlite3
printf 'Installer, native bridge and uninstaller checks passed.\n'
