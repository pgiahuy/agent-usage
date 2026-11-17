#!/usr/bin/env bash
# Why the panel indicator is not showing. Read-only: it changes nothing, and
# prints the command to run for each thing it finds.
#
# The usual answers, in the order they bite:
#   1. the session has not been restarted since the extension was installed
#   2. user extensions are switched off for the whole session
#   3. GNOME Shell is outside the range metadata.json declares
set -uo pipefail

UUID=agent-usage@pgiahuy.github.io
USER_EXT=${XDG_DATA_HOME:-$HOME/.local/share}/gnome-shell/extensions/$UUID
SYS_EXT=/usr/share/gnome-shell/extensions/$UUID
# GNOME Shell loads from both. The per-user copy shadows the system one, so it
# is the one that runs when both are present.
if [ -d "$USER_EXT" ]; then
  EXT=$USER_EXT
  REINSTALL="run ./install.sh again from the checkout"
elif [ -d "$SYS_EXT" ]; then
  EXT=$SYS_EXT
  REINSTALL="reinstall the package: sudo apt install --reinstall agent-usage"
else
  EXT=$USER_EXT
  REINSTALL="run ./install.sh from a checkout, or install the .deb"
fi
STATE=${XDG_CACHE_HOME:-$HOME/.cache}/agent-usage/state.json
problems=0

ok()   { printf '  ok    %s\n' "$*"; }
info() { printf '  ..    %s\n' "$*"; }
bad()  { printf '  >>    %s\n' "$*"; problems=$((problems + 1)); }

echo "== session =="
info "desktop: ${XDG_CURRENT_DESKTOP:-unset}, session: ${XDG_SESSION_TYPE:-unset}"
if [ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ]; then
  ok "session D-Bus is reachable"
else
  bad "no session D-Bus, so gsettings cannot work here. You are in a plain"
  bad "tty or on an ssh connection; run this inside the desktop session."
fi

echo "== gnome shell =="
if command -v gnome-shell >/dev/null 2>&1; then
  running=$(gnome-shell --version 2>/dev/null | grep -o '[0-9][0-9]*' | head -1)
  info "running GNOME Shell ${running:-unknown}"
  if [ -r "$EXT/metadata.json" ]; then
    declared=$(tr -d '\n' < "$EXT/metadata.json" \
      | sed -n 's/.*"shell-version"[^[]*\[\([^]]*\)\].*/\1/p' | tr -d ' "')
    info "the installed extension declares $declared"
    case ",$declared," in
      *",$running,"*) ok "the versions match" ;;
      *)
        bad "version mismatch: GNOME Shell $running is not in that list, so the"
        bad "shell refuses to load the extension and reports nothing."
        if [ "$EXT" = "$SYS_EXT" ]; then
          bad "The package needs a release that lists $running; check for one"
          bad "at https://github.com/pgiahuy/agent-usage/releases"
        else
          bad "Add \"$running\" to shell-version in extension/metadata.json,"
          bad "then $REINSTALL, and log out and back in."
        fi
        ;;
    esac
  else
    bad "no metadata.json under $EXT, so the extension is not installed."
    bad "To install it, $REINSTALL."
  fi
else
  bad "gnome-shell is not installed on this machine. The collector and the"
  bad "'agent-usage' terminal view still work; the panel indicator cannot."
fi

echo "== the session-wide switch =="
if command -v gsettings >/dev/null 2>&1; then
  master=$(gsettings get org.gnome.shell disable-user-extensions 2>/dev/null)
  case "$master" in
    false)
      ok "user extensions are allowed"
      ;;
    true)
      bad "disable-user-extensions is true, which switches off every"
      bad "user-installed extension whatever else is set. Turn them back on:"
      bad "  gsettings set org.gnome.shell disable-user-extensions false"
      ;;
    *)
      bad "cannot read org.gnome.shell: either the schema is missing or there"
      bad "is no session bus here."
      ;;
  esac
  case "$(gsettings get org.gnome.shell enabled-extensions 2>/dev/null)" in
    *"'$UUID'"*) ok "listed in enabled-extensions" ;;
    *)
      bad "not listed in enabled-extensions. Add it with:"
      bad "  gnome-extensions enable $UUID"
      ;;
  esac
else
  bad "gsettings is missing. Install it: libglib2.0-bin"
fi

echo "== the installed extension =="
if [ -d "$EXT" ]; then
  ok "files are in $EXT"
  for f in extension.js metadata.json stylesheet.css prefs.js schemas/gschemas.compiled; do
    if [ -e "$EXT/$f" ]; then
      ok "  $f"
    else
      bad "  $f is missing. To fix it, $REINSTALL."
    fi
  done
  newest_ui=""
  for f in "$EXT"/ui-*.js; do
    if [ -e "$f" ]; then newest_ui=$f; fi
  done
  if [ -n "$newest_ui" ]; then
    ok "  $(basename "$newest_ui")"
  else
    bad "  no ui-<n>.js, which is the whole user interface. To fix it, $REINSTALL."
  fi
else
  bad "The extension is not installed in either place GNOME looks:"
  bad "  $USER_EXT"
  bad "  $SYS_EXT"
  bad "To install it, $REINSTALL."
fi

if command -v gnome-extensions >/dev/null 2>&1; then
  state=$(gnome-extensions info "$UUID" 2>/dev/null | sed -n 's/^ *State: //p')
  case "$state" in
    ACTIVE)
      ok "state: ACTIVE"
      ;;
    "")
      bad "the running shell has never heard of this extension, which means it"
      bad "has not rescanned since the install. Log out and back in once."
      ;;
    *)
      bad "state: $state. The shell knows it but is not running it. Try:"
      bad "  gnome-extensions enable $UUID"
      bad "and read why in: journalctl --user -b | grep -i agent-usage"
      ;;
  esac
else
  bad "the gnome-extensions command is missing. On Debian and Ubuntu it comes"
  bad "with gnome-shell itself."
fi

echo "== the collector =="
if command -v systemctl >/dev/null 2>&1; then
  info "service: $(systemctl --user is-active agent-usage 2>&1), $(systemctl --user is-enabled agent-usage 2>&1)"
fi
if [ -r "$STATE" ]; then
  ok "state.json was written $(( $(date +%s) - $(stat -c %Y "$STATE") ))s ago"
elif [ "$(systemctl --user is-active agent-usage 2>/dev/null)" = active ]; then
  # The first pass reads the whole window rather than a tail, which on a large
  # log takes the better part of a minute. Running right after an install, that
  # is not a fault yet, so it is reported as waiting rather than broken.
  info "no state.json yet, but the collector is running: the first pass reads"
  info "every log in the window and can take a minute. Re-run this if the panel"
  info "is still empty after that."
else
  bad "no $STATE and the collector is not running. Start it and read why in:"
  bad "  systemctl --user start agent-usage"
  bad "  journalctl --user -u agent-usage -n 30"
fi

echo "== what the journal says about it this boot =="
if ! journalctl --user -b --no-pager 2>/dev/null | grep -i 'agent-usage' | tail -5; then
  info "nothing, which is normal when the shell has not tried to load it yet"
fi

echo
if [ "$problems" -eq 0 ]; then
  echo "Nothing wrong found. If the panel is still empty, the indicator may be"
  echo "hidden by another extension that manages the top bar."
else
  echo "$problems thing(s) to deal with, marked >> above."
fi
