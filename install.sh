#!/usr/bin/env bash
# Install agent-usage into the current user's home. No root, nothing outside
# $HOME. Re-running it is the upgrade path.
set -euo pipefail

UUID=agent-usage@pgiahuy.github.io
SRC=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
CONFIG_HOME=${XDG_CONFIG_HOME:-$HOME/.config}
BIN_DIR=$HOME/.local/bin
APP_DIR=$DATA_HOME/agent-usage
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
                 yourself with: agent-usage --daemon
EOF
      exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '  %s\n' "$*"; }

# --- python ---------------------------------------------------------------
# The collector is standard library only, so any python3 >= 3.8 runs it. The
# system interpreter comes first: a pyenv or conda python on PATH can be
# switched or removed later, and the service would stop with it.
pick_python() {
  local candidate
  for candidate in /usr/bin/python3 "$(command -v python3 || true)"; do
    [ -x "$candidate" ] || continue
    "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null || continue
    echo "$candidate"
    return 0
  done
  return 1
}

PYTHON=$(pick_python) || {
  echo "agent-usage: no python3 >= 3.8 found" >&2
  exit 1
}

echo "agent-usage: installing"
say "python:    $PYTHON"

# --- gnome shell version --------------------------------------------------
# Read out of metadata.json rather than written again here, so the check and
# what the shell actually enforces cannot drift apart. A shell outside the
# declared range refuses to load the extension and says nothing about why,
# and that is true above the range as well as below it.
declared_shell_versions() {
  tr -d '\n' < "$SRC/extension/metadata.json" \
    | sed -n 's/.*"shell-version"[^[]*\[\([^]]*\)\].*/\1/p' | tr -d ' "'
}

if command -v gnome-shell >/dev/null 2>&1; then
  shell_version=$(gnome-shell --version 2>/dev/null | grep -o '[0-9][0-9]*' | head -1)
  declared=$(declared_shell_versions)
  say "gnome shell: ${shell_version:-unknown}"
  if [ -n "${shell_version:-}" ] && [ -n "$declared" ]; then
    case ",$declared," in
      *",$shell_version,"*) ;;
      *)
        say "warning: the extension declares GNOME Shell $declared and this"
        say "         session is $shell_version, so the shell will refuse to"
        say "         load it. The collector and the 'agent-usage' terminal"
        say "         view work on any version. To try it anyway, add"
        say "         \"$shell_version\" to shell-version in"
        say "         extension/metadata.json and run this again."
        ;;
    esac
  fi
else
  say "gnome shell: not found, installing the collector and CLI only"
fi

# --- collector ------------------------------------------------------------
# Wiped first, so a module a newer version dropped does not linger.
rm -rf "$APP_DIR"
install -d "$APP_DIR/providers" "$BIN_DIR" "$UNIT_DIR"
install -m 644 "$SRC"/daemon/*.py "$APP_DIR/"
install -m 644 "$SRC"/daemon/providers/*.py "$APP_DIR/providers/"

sed -e "s|@PYTHON@|$PYTHON|" -e "s|@APP_DIR@|$APP_DIR|" \
    "$SRC/bin/agent-usage.in" > "$BIN_DIR/agent-usage"
chmod 755 "$BIN_DIR/agent-usage"
say "collector: $APP_DIR"
say "command:   $BIN_DIR/agent-usage"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) say "note: $BIN_DIR is not on your PATH" ;;
esac

# --- extension ------------------------------------------------------------
# The running shell has imported ui-<n>.js by its file name and will never
# re-read that name, so an update that changes the UI is installed under a
# number above every one already there; extension.js, the loader, then picks
# it up on disable/enable, below, with no logout. An unchanged UI keeps its
# name, so nothing reloads for no reason.
ui_num() { local f; f=$(basename "$1"); f=${f#ui-}; echo "${f%.js}"; }
newest_ui() {
  local f best="" n=-1
  for f in "$1"/ui-*.js; do
    [ -e "$f" ] || continue
    [ "$(ui_num "$f")" -gt "$n" ] 2>/dev/null && { n=$(ui_num "$f"); best=$f; }
  done
  echo "$best"
}
src_ui=$(newest_ui "$SRC/extension")
ui_target=$(ui_num "$src_ui")
old_ui=$(newest_ui "$EXT_DIR")
reload_ui=0
needs_login=0
if [ -n "$old_ui" ]; then
  old_n=$(ui_num "$old_ui")
  if cmp -s "$src_ui" "$old_ui"; then
    ui_target=$old_n
  else
    reload_ui=1
    [ "$ui_target" -gt "$old_n" ] || ui_target=$((old_n + 1))
  fi
  # The stylesheet needs no new name: enable re-reads it.
  cmp -s "$SRC/extension/stylesheet.css" "$EXT_DIR/stylesheet.css" || reload_ui=1
  # What the shell read once, at login, and does not re-read on enable: the
  # loader module, the metadata, and whether prefs.js exists at all.
  for f in extension.js metadata.json; do
    cmp -s "$SRC/extension/$f" "$EXT_DIR/$f" || needs_login=1
  done
  [ -e "$EXT_DIR/prefs.js" ] || needs_login=1
fi

# Wiped rather than merged, so no stale ui-<n>.js outranks the one written now.
rm -rf "$EXT_DIR"
install -d "$EXT_DIR/schemas"
for f in "$SRC"/extension/*.js "$SRC"/extension/*.json "$SRC"/extension/*.css; do
  case $(basename "$f") in ui-*.js) continue ;; esac
  install -m 644 "$f" "$EXT_DIR/"
done
install -m 644 "$src_ui" "$EXT_DIR/ui-$ui_target.js"
install -m 644 "$SRC"/extension/schemas/*.gschema.xml "$EXT_DIR/schemas/"
if command -v glib-compile-schemas >/dev/null 2>&1; then
  glib-compile-schemas "$EXT_DIR/schemas"
else
  say "warning: glib-compile-schemas not found (package libglib2.0-bin);"
  say "         the extension will not load its settings until it is"
fi
say "extension: $EXT_DIR"

# --- service --------------------------------------------------------------
if [ "$with_service" -eq 1 ]; then
  install -m 644 "$SRC/systemd/agent-usage.service" "$UNIT_DIR/agent-usage.service"
  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload
    systemctl --user enable --now agent-usage.service
    say "service:   $(systemctl --user is-active agent-usage.service)"
  else
    say "service:   systemd not found; run 'agent-usage --daemon' yourself"
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

ext_state() {
  gnome-extensions info "$UUID" 2>/dev/null | sed -n 's/^ *State: //p'
}

# The shell carries out a disable or an enable after the command has returned.
# An enable sent while the disable is still under way can be lost, leaving the
# extension switched on in the settings but INACTIVE, so each step waits for
# the state it asked for (up to 5s) before the next one goes out.
wait_state() {
  local tries=50
  while [ "$tries" -gt 0 ]; do
    [ "$(ext_state)" = "$1" ] && return 0
    sleep 0.1
    tries=$((tries - 1))
  done
  return 1
}

reload_extension() {
  gnome-extensions disable "$UUID" 2>/dev/null || true
  wait_state INACTIVE || true
  gnome-extensions enable "$UUID" || true
  wait_state ACTIVE
}

# This one switch beats every per-extension setting: with it on, nothing
# user-installed loads and the panel stays empty with nothing in any log to
# say why. Reported rather than flipped, because turning it off would also
# switch back on every other extension the user had turned off on purpose.
if command -v gsettings >/dev/null 2>&1 \
   && [ "$(gsettings get org.gnome.shell disable-user-extensions 2>/dev/null)" = true ]; then
  say "warning: user extensions are switched off for this session, so none"
  say "         will load. Turn them back on with:"
  say "           gsettings set org.gnome.shell disable-user-extensions false"
fi

echo
if command -v gnome-extensions >/dev/null 2>&1 && gnome-extensions info "$UUID" >/dev/null 2>&1; then
  # Known to the running shell, so this is an update: a disable/enable loads
  # the new ui-<n>.js and re-reads stylesheet.css.
  if [ "$reload_ui" -eq 1 ]; then
    reload_extension || reload_extension || true
  else
    gnome-extensions enable "$UUID" || true
    wait_state ACTIVE || true
  fi
  state=$(ext_state)
  if [ "$state" != ACTIVE ]; then
    echo "Done, but the panel indicator did not come back on (state: ${state:-unknown})."
    echo "Run:  gnome-extensions enable $UUID"
    echo "and if it still does not appear: journalctl --user -b | grep -i agent-usage"
  elif [ "$needs_login" -eq 1 ]; then
    [ "$reload_ui" -eq 1 ] && echo "Done. The panel indicator has been reloaded with the new version,"
    [ "$reload_ui" -eq 1 ] || echo "Done."
    echo "but extension.js, metadata.json or the preferences page changed, and"
    echo "GNOME Shell reads those only at login: log out and back in once to"
    echo "finish the update."
  elif [ "$reload_ui" -eq 1 ]; then
    echo "Done. The panel indicator has been reloaded with the new version."
  else
    echo "Done. The panel indicator is enabled."
  fi
elif enable_in_dconf; then
  echo "Done. Log out and back in once; the indicator comes up with the session."
  echo "(GNOME Shell only looks for new extensions when the session starts.)"
else
  echo "Done, except for one step this script could not do:"
  echo
  echo "  log out and back in, then run:  gnome-extensions enable $UUID"
  echo
  echo "If the indicator still does not appear, ./tools/doctor.sh says why."
fi
echo "Check the numbers from a terminal any time with: agent-usage"
