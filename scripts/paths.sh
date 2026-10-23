# Sourced by the install scripts. Same rule as the agent: empty or relative XDG values are ignored.
xdg_dir() {
  local value="${!1:-}"
  if [[ "$value" == /* ]]; then printf '%s' "$value"; else printf '%s' "$2"; fi
}
data_home="$(xdg_dir XDG_DATA_HOME "$HOME/.local/share")"
config_home="$(xdg_dir XDG_CONFIG_HOME "$HOME/.config")"
state_home="$(xdg_dir XDG_STATE_HOME "$HOME/.local/state")"
install_dir="$data_home/focus-ratio"
