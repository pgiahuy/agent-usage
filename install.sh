#!/usr/bin/env bash
# Install ai-usage into the current user's home. No root, nothing outside
# $HOME. Re-running it is the upgrade path.
set -euo pipefail

UUID=ai-usage@pgiahuy.github.io
SRC=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
CONFIG_HOME=${XDG_CONFIG_HOME:-$HOME/.config}
BIN_DIR=$HOME/.local/bin
APP_DIR=$DATA_HOME/ai-usage
EXT_DIR=$DATA_HOME/gnome-shell/extensions/$UUID
UNIT_DIR=$CONFIG_HOME/systemd/user

with_service=1
for arg in "$@"; do
  case $arg in
    --no-service) with_service=0 ;;
    -h|--help)
      cat <<EOF
usage: ./install.sh [--no-service]

  --no-service   copy the files but do not touch systemd; start the collector
                 yourself with: ai-usage --daemon
EOF
      exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '  %s\n' "$*"; }

# --- python ---------------------------------------------------------------
# The collector is standard library only, so any python3 will run it. The
# optional --tray fallback needs PyGObject, which on most distributions only
# the system interpreter has: a pyenv or conda python will not do. Prefer an
# interpreter that has it, and fall back to whatever is on PATH.
pick_python() {
  local best=""
  for candidate in /usr/bin/python3 "$(command -v python3 || true)"; do
    [ -x "$candidate" ] || continue
    "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null || continue
    if "$candidate" -c 'import gi' 2>/dev/null; then
      echo "$candidate"
      return 0
    fi
    [ -n "$best" ] || best=$candidate
  done
  [ -n "$best" ] || return 1
  echo "$best"
}

PYTHON=$(pick_python) || {
  echo "ai-usage: no python3 >= 3.8 found" >&2
  exit 1
}

echo "ai-usage: installing"
say "python:    $PYTHON"

# --- gnome shell version --------------------------------------------------
if command -v gnome-shell >/dev/null 2>&1; then
  shell_version=$(gnome-shell --version 2>/dev/null | grep -o '[0-9][0-9]*' | head -1)
  say "gnome shell: ${shell_version:-unknown}"
  if [ -n "${shell_version:-}" ] && [ "$shell_version" -lt 48 ] 2>/dev/null; then
    say "warning: the extension needs GNOME Shell 48 or newer (St.BoxLayout"
    say "         gained the orientation property there). The collector and"
    say "         the 'ai-usage' terminal view work on any version."
  fi
else
  say "gnome shell: not found, installing the collector and CLI only"
fi

# --- collector ------------------------------------------------------------
install -d "$APP_DIR" "$BIN_DIR" "$UNIT_DIR"
install -m 644 "$SRC"/daemon/*.py "$APP_DIR/"
rm -rf "$APP_DIR/__pycache__"

sed -e "s|@PYTHON@|$PYTHON|" -e "s|@APP_DIR@|$APP_DIR|" \
    "$SRC/bin/ai-usage.in" > "$BIN_DIR/ai-usage"
chmod 755 "$BIN_DIR/ai-usage"
say "collector: $APP_DIR"
say "command:   $BIN_DIR/ai-usage"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) say "note: $BIN_DIR is not on your PATH" ;;
esac

# --- extension ------------------------------------------------------------
# Wiped rather than merged: the loader imports the highest-numbered ui-<n>.js
# it can find, so a stale ui-9.js from a previous version would win over the
# one being installed now.
rm -rf "$EXT_DIR"
install -d "$EXT_DIR"
install -m 644 "$SRC"/extension/* "$EXT_DIR/"
say "extension: $EXT_DIR"

# --- service --------------------------------------------------------------
if [ "$with_service" -eq 1 ]; then
  install -m 644 "$SRC/systemd/ai-usage.service" "$UNIT_DIR/ai-usage.service"
  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload
    systemctl --user enable --now ai-usage.service
    say "service:   $(systemctl --user is-active ai-usage.service)"
  else
    say "service:   systemd not found; run 'ai-usage --daemon' yourself"
  fi
fi

# --- enabling the extension ----------------------------------------------
# GNOME Shell scans the extensions directory once, at startup, and caches every
# module it imports for the life of the process. A brand new extension is
# therefore invisible until the session restarts: there is no reload D-Bus
# call any more.
# `gnome-extensions enable` refuses a uuid the running shell has never heard
# of, but the setting it writes is just a list in dconf, and the shell reads
# that list at startup, after it has scanned the directory. Writing it
# ourselves means the extension is already on at the next login, instead of
# needing a second command afterwards.
enable_in_dconf() {
  command -v gsettings >/dev/null 2>&1 || return 1
  local current
  current=$(gsettings get org.gnome.shell enabled-extensions 2>/dev/null) || return 1
  case "$current" in
    *"'$UUID'"*) return 0 ;;                                   # already listed
    "@as []"|"[]") gsettings set org.gnome.shell enabled-extensions "['$UUID']" ;;
    \[*\]) gsettings set org.gnome.shell enabled-extensions "${current%]}, '$UUID']" ;;
    *) return 1 ;;
  esac
}

echo
if command -v gnome-extensions >/dev/null 2>&1 && gnome-extensions info "$UUID" >/dev/null 2>&1; then
  gnome-extensions enable "$UUID" || true
  echo "Done. The panel indicator is enabled."
  echo "If it does not appear, log out and back in once."
elif enable_in_dconf; then
  echo "Done. Log out and back in once; the indicator comes up with the session."
  echo "(GNOME Shell only looks for new extensions when the session starts.)"
else
  echo "Done, except for one step this script could not do:"
  echo
  echo "  log out and back in, then run:  gnome-extensions enable $UUID"
fi
echo "Check the numbers from a terminal any time with: ai-usage"
