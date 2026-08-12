#!/usr/bin/env bash
# Remove everything install.sh put in place.
set -euo pipefail

UUID=ai-usage@local
DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
CONFIG_HOME=${XDG_CONFIG_HOME:-$HOME/.config}
CACHE_HOME=${XDG_CACHE_HOME:-$HOME/.cache}

purge=0
for arg in "$@"; do
  case $arg in
    --purge) purge=1 ;;
    -h|--help)
      echo "usage: ./uninstall.sh [--purge]"
      echo "  --purge   also delete $CACHE_HOME/ai-usage (cached readings and icons)"
      exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

if command -v systemctl >/dev/null 2>&1; then
  systemctl --user disable --now ai-usage.service 2>/dev/null || true
fi
rm -f "$CONFIG_HOME/systemd/user/ai-usage.service"
command -v systemctl >/dev/null 2>&1 && systemctl --user daemon-reload || true

if command -v gnome-extensions >/dev/null 2>&1; then
  gnome-extensions disable "$UUID" 2>/dev/null || true
fi

rm -rf "$DATA_HOME/gnome-shell/extensions/$UUID"
rm -rf "$DATA_HOME/ai-usage"
rm -f "$HOME/.local/bin/ai-usage"
[ "$purge" -eq 1 ] && rm -rf "$CACHE_HOME/ai-usage"

echo "ai-usage: removed."
[ "$purge" -eq 1 ] || echo "Cached readings left in $CACHE_HOME/ai-usage (--purge removes them)."
echo "Nothing was touched in ~/.claude or ~/.kimi-code."
