#!/usr/bin/env bash
# Real Chromium + native host; installer service-manager calls are recorded, not executed.
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
for command in bwrap chromium node python3 systemd-analyze; do
  command -v "$command" >/dev/null
done
scratch_dir="$(mktemp -d /tmp/focus-isolated.XXXXXX)"
trap 'rm -rf -- "$scratch_dir"' EXIT
bwrap --unshare-all --die-with-parent \
  --ro-bind /usr /usr --ro-bind /etc /etc --ro-bind /sys /sys \
  --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib /lib64 \
  --proc /proc --dev /dev --tmpfs /tmp \
  --ro-bind "$repo_dir" /project --bind "$scratch_dir" /test \
  --chdir /project /bin/bash /project/tests/isolated-install.sh
mkdir -p "$repo_dir/dist/isolated-check"
for file in extension-connected.png extension-offline.png browser-result.json unit-check.log systemctl-requests.log; do
  install -m 0644 "$scratch_dir/$file" "$repo_dir/dist/isolated-check/$file"
done
printf 'Results: %s/dist/isolated-check\n' "$repo_dir"
