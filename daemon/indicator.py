#!/usr/bin/env python3
"""GNOME top-bar indicator for Claude Code + Kimi Code usage.

Panel: a ring gauge of Claude's 5-hour window, coloured by severity, plus a
short label. Click it for the full breakdown: quota bars with reset times, and
tokens spent today / over the last 7 days for both tools, split by model.

Run:  agent-usage --tray        (normally started by systemctl --user)
"""
from __future__ import annotations

import os
import signal
import sys
import threading

import gi

try:
    gi.require_version("Gtk", "3.0")
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
except ValueError:
    try:
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3 as AppIndicator
    except ValueError:
        sys.stderr.write(
            "AppIndicator bindings are missing. Install them with:\n"
            "  sudo apt install -y gir1.2-ayatanaappindicator3-0.1\n"
        )
        sys.exit(1)

from gi.repository import GLib, Gtk  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ring  # noqa: E402
import rows  # noqa: E402
import usage_core as core  # noqa: E402

APP_ID = "agent-usage"
FALLBACK_ICON = "utilities-system-monitor-symbolic"
LABEL_GUIDE = "100% · wk 100% · K 000M"
LOCAL_REFRESH_S = 20  # rescan logs (near-free once offsets are warm)
QUOTA_REFRESH_S = 300  # hit the quota APIs (endpoint is rate limited, go easy)

class Indicator:
    def __init__(self):
        self.collector = core.Collector()
        self.local = {}
        self.quota = {
            "claude": {"ok": False, "why": "loading"},
            "kimi": {"ok": False, "why": "loading"},
        }
        self._fetching = False
        self._icon = None

        self.ind = AppIndicator.Indicator.new(
            APP_ID, FALLBACK_ICON, AppIndicator.IndicatorCategory.SYSTEM_SERVICES
        )
        self.ind.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.ind.set_title("Agent usage")
        self.menu = Gtk.Menu()
        self.ind.set_menu(self.menu)
        self.ind.set_label("…", LABEL_GUIDE)

        self.refresh_local()
        self.refresh_quota()
        GLib.timeout_add_seconds(LOCAL_REFRESH_S, self._tick_local)
        GLib.timeout_add_seconds(QUOTA_REFRESH_S, self._tick_quota)

    # -- refresh loop --------------------------------------------------------

    def _tick_local(self):
        self.refresh_local()
        return True

    def _tick_quota(self):
        self.refresh_quota()
        return True

    def refresh_local(self):
        """Log scan is fast enough (offsets live in memory) to run on the main loop."""
        try:
            self.local = self.collector.local()
        except Exception as exc:  # the indicator must never die
            sys.stderr.write("agent-usage: log scan failed: %r\n" % (exc,))
            return
        self._render()

    def refresh_quota(self, force=False):
        """Network calls go to a worker thread; never block the GTK main loop."""
        if self._fetching:
            return
        self._fetching = True
        # An explicit Refresh should mostly bypass the shared cache, but not so
        # far that repeated clicking walks into the endpoint's rate limit.
        fresh_for = 30 if force else core.QUOTA_FRESH_S

        def work():
            try:
                result = {
                    "claude": core.claude_quota(fresh_for=fresh_for),
                    "kimi": core.kimi_quota(fresh_for=fresh_for),
                }
            except Exception as exc:
                result = {
                    "claude": {"ok": False, "why": repr(exc)},
                    "kimi": {"ok": False, "why": repr(exc)},
                }
            GLib.idle_add(self._quota_done, result)

        threading.Thread(target=work, daemon=True).start()

    def _quota_done(self, result):
        self._fetching = False
        self.quota = result
        self._render()
        return False

    def _render(self):
        if not self.local:
            return
        self._update_icon()
        self.ind.set_label(rows.panel_label(self.local, self.quota), LABEL_GUIDE)
        self._rebuild_menu()

    # -- panel ---------------------------------------------------------------

    def _update_icon(self):
        session, _live = rows.session_limit(self.quota)
        if session:
            path = ring.write_icon(
                core.CACHE_DIR, session["percent"] or 0, session["severity"], known=True
            )
        else:
            path = ring.write_icon(core.CACHE_DIR, 0, "normal", known=False)
        if path and path != self._icon:
            self._icon = path
            self.ind.set_icon_full(path, "Agent usage")

    # -- menu ----------------------------------------------------------------

    def _row(self, markup, indent=0):
        item = Gtk.MenuItem()
        label = Gtk.Label()
        label.set_markup(("    " * indent) + markup)
        label.set_xalign(0.0)
        item.add(label)
        # Deliberately left sensitive: set_sensitive(False) would dim the whole
        # row to ~50% opacity and wash out the severity colours these rows exist
        # to convey. They simply do nothing when activated.
        self.menu.append(item)

    def _rebuild_menu(self):
        for child in self.menu.get_children():
            self.menu.remove(child)

        for entry in rows.build(self.local, self.quota):
            if entry is None:
                self.menu.append(Gtk.SeparatorMenuItem())
            else:
                self._row(*entry)

        self.menu.append(Gtk.SeparatorMenuItem())
        refresh = Gtk.MenuItem(label="Refresh")
        refresh.connect("activate", lambda _w: (self.refresh_local(), self.refresh_quota(True)))
        self.menu.append(refresh)
        # No Quit item on purpose: this is a always-on readout, and the unit is
        # Restart=always, so quitting from the menu would only make it vanish
        # for five seconds. Stop it deliberately with:
        #   systemctl --user stop agent-usage
        self.menu.show_all()


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    Indicator()
    Gtk.main()


if __name__ == "__main__":
    main()
