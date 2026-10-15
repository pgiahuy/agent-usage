#!/usr/bin/env python3
"""Headless collector: keep ~/.cache/agent-usage/state.json current.

The GNOME Shell extension is pure presentation: it reads this file and draws.
Keeping the log parsing and the quota calls here means the shell process never
touches 400 MB of jsonl, and the numbers stay in the one place they have been
verified.

Writes are atomic (temp file + rename) so a reader never sees a half file.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ring  # noqa: E402
import usage_core as core  # noqa: E402

STATE_PATH = os.path.join(core.CACHE_DIR, "state.json")
# The extension touches this to ask for an immediate refresh; a watched file
# keeps the shell from having to spawn a process or send a signal.
TRIGGER_PATH = os.path.join(core.CACHE_DIR, "refresh-request")
LOCAL_EVERY = 20
QUOTA_EVERY = 300  # used when the extension's settings cannot be read

# The user's choices live in the extension's GSettings schema. The collector is
# standard library only, so it reads them with the gsettings command; the
# schema is compiled inside the extension, hence --schemadir.
SCHEMA = "org.gnome.shell.extensions.agent-usage"
_UUID = "agent-usage@pgiahuy.github.io"
_SCHEMA_DIRS = (
    os.path.join(os.environ.get("XDG_DATA_HOME", os.path.join(core.HOME, ".local", "share")),
                 "gnome-shell", "extensions", _UUID, "schemas"),
    os.path.join("/usr/share/gnome-shell/extensions", _UUID, "schemas"),
)
# An explicit Refresh should mostly bypass the shared quota cache, but not so
# far that repeated clicking walks into the endpoint's rate limit.
FORCED_FRESH_S = 30

_running = True


def _stop(_sig, _frm):
    global _running
    _running = False


def _totals(side, key):
    t = side[key]["total"]
    total = core.total_tokens(t)
    # tokens_h is pre-formatted here so the shell process never has to reproduce
    # the abbreviation rules and drift from what the CLI prints.
    return {
        "tokens": total,
        "tokens_h": core.fmt_tokens(total),
        "reqs": t["reqs"],
        **{f: t[f] for f in core.FIELDS},
    }


def _models(side):
    ranked = sorted(side["today"]["by_model"].items(), key=lambda kv: -core.total_tokens(kv[1]))
    return [
        {
            "name": core.short_model(m),
            "tokens": core.total_tokens(t),
            "reqs": t["reqs"],
        }
        for m, t in ranked[:4]
    ]


def _fetch_quota(fresh_for=None, renew=False):
    """Both providers, never raising. renew lets an expired token be renewed,
    which only an explicit Refresh asks for.

    An unexpected error escaping here would end the process, and the unit is
    Restart=always, so the daemon would respawn every RestartSec for as long as
    the cause lasted. The reason goes to the journal in full; the panel gets a
    short version that fits its one line.
    """
    out = {}
    for tag, fetch in (("claude", core.claude_quota), ("kimi", core.kimi_quota)):
        try:
            kw = {"renew": renew}
            if fresh_for is not None:
                kw["fresh_for"] = fresh_for
            out[tag] = fetch(**kw)
        except Exception as exc:
            sys.stderr.write("agent-usage: %s quota failed: %r\n" % (tag, exc))
            out[tag] = {"ok": False, "why": "error: " + type(exc).__name__}
    return out


def _tool_state(name, side, quota, tag):
    raw_limits, live, why = core.live_limits(quota)
    limits = [
        {
            "label": lim["label"],
            "percent": lim["percent"] or 0,
            "severity": lim["severity"],
            "colour": ring.severity_color(lim["percent"], lim["severity"]),
            "resets": core.fmt_reset(lim["resets_at"]),
        }
        for lim in raw_limits
    ]
    session = next((l for l in limits if l["label"].startswith("5-hour")), None)
    accent = ring.CLAUDE if tag == "claude" else ring.KIMI
    icon = ring.write_icon(
        core.CACHE_DIR,
        session["percent"] if session else 0,
        session["severity"] if session else "normal",
        known=session is not None,
        tag=tag,
        accent=accent,
    )
    return {
        "name": name,
        "accent": accent,
        "limits": limits,
        "live": live,
        "why": why,
        "icon": icon,
        # What the panel shows next to the ring: the 5-hour percent when we have
        # it, otherwise today's token volume, never a fabricated percentage.
        "badge": ("%d%%" % session["percent"]) if session else core.fmt_tokens(
            core.total_tokens(side["today"]["total"])
        ),
        "badge_is_percent": session is not None,
        "stale": not live and bool(limits),
        "today": _totals(side, "today"),
        "week": _totals(side, "week"),
        "models": _models(side),
    }


def build_state(collector, quota):
    local = collector.local()
    return {
        "at": time.time(),
        "tools": [
            _tool_state("CLAUDE", local["claude"], quota["claude"], "claude"),
            _tool_state("KIMI", local["kimi"], quota["kimi"], "kimi"),
        ],
    }


def write_state(state):
    os.makedirs(core.CACHE_DIR, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh)
    os.replace(tmp, STATE_PATH)


def setting(key):
    """One key from the extension's settings, as gsettings prints it, or None."""
    for schema_dir in _SCHEMA_DIRS:
        if not os.path.exists(os.path.join(schema_dir, "gschemas.compiled")):
            continue
        try:
            out = subprocess.run(
                ["gsettings", "--schemadir", schema_dir, "get", SCHEMA, key],
                capture_output=True, text=True, timeout=5, check=True,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
        return out or None
    return None


def quota_every():
    # A uint32 prints as "uint32 5".
    raw = setting("quota-interval")
    try:
        return int(raw.split()[-1]) * 60
    except (AttributeError, ValueError, IndexError):
        return QUOTA_EVERY


def _trigger_mtime():
    try:
        return os.path.getmtime(TRIGGER_PATH)
    except OSError:
        return 0.0


def main():
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    collector = core.Collector()
    quota = {"claude": {"ok": False, "why": "starting"}, "kimi": {"ok": False, "why": "starting"}}
    last_quota = 0.0
    seen_trigger = _trigger_mtime()

    while _running:
        forced = False
        now = time.time()
        if now - last_quota >= quota_every() or last_quota == 0.0:
            quota = _fetch_quota()
            last_quota = now
        try:
            write_state(build_state(collector, quota))
        except Exception as exc:  # a bad cycle must not kill the daemon
            sys.stderr.write("agent-usage: state write failed: %r\n" % (exc,))

        # Wake every second so SIGTERM lands promptly and a Refresh click is
        # picked up without waiting out the whole interval.
        for _ in range(LOCAL_EVERY):
            if not _running:
                break
            stamp = _trigger_mtime()
            if stamp != seen_trigger:
                seen_trigger = stamp
                quota = _fetch_quota(FORCED_FRESH_S, renew=True)
                last_quota = time.time()
                forced = True
                break
            time.sleep(1)
        if forced:
            continue
    return 0


if __name__ == "__main__":
    sys.exit(main())
