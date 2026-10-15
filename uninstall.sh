#!/usr/bin/env bash
# Remove everything install.sh put in place.
set -euo pipefail

UUID=agent-usage@pgiahuy.github.io
DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
CONFIG_HOME=${XDG_CONFIG_HOME:-$HOME/.config}
CACHE_HOME=${XDG_CACHE_HOME:-$HOME/.cache}

purge=0
for arg in "$@"; do
  case $arg in
    --purge) purge=1 ;;
    -h|--help)
      echo "usage: ./uninstall.sh [--purge]"
      echo "  --purge   also delete $CACHE_HOME/agent-usage (cached readings and icons)"
      echo "            and reset the extension's settings"
      exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

if command -v systemctl >/dev/null 2>&1; then
  systemctl --user disable --now agent-usage.service 2>/dev/null || true
fi
rm -f "$CONFIG_HOME/systemd/user/agent-usage.service"
command -v systemctl >/dev/null 2>&1 && systemctl --user daemon-reload || true

# Asking the shell to uninstall unloads the extension from the running session
# and deletes it, so the indicator is gone at once. disable first takes it out
# of the enabled list too. Without a shell to ask, the files are removed and the
# indicator, already loaded, stays until the next login.
live_removed=0
if command -v gnome-extensions >/dev/null 2>&1; then
  gnome-extensions disable "$UUID" 2>/dev/null || true
  gnome-extensions uninstall "$UUID" 2>/dev/null && live_removed=1
fi
rm -rf "$DATA_HOME/gnome-shell/extensions/$UUID"
rm -rf "$DATA_HOME/agent-usage"
rm -f "$HOME/.local/bin/agent-usage"
if [ "$purge" -eq 1 ]; then
  rm -rf "$CACHE_HOME/agent-usage"
  command -v dconf >/dev/null 2>&1 && dconf reset -f /org/gnome/shell/extensions/agent-usage/ || true
fi

echo "agent-usage: removed."
[ "$live_removed" -eq 1 ] || echo "The panel indicator, if it was showing, disappears at the next login."
[ "$purge" -eq 1 ] || echo "Cached readings left in $CACHE_HOME/agent-usage (--purge removes them)."
echo "Nothing was touched in ~/.claude or ~/.kimi-code."
