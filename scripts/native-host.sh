#!/usr/bin/env bash
set -euo pipefail

install_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$install_dir/focus_ratio_agent.py" --native-host
