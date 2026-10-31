#!/usr/bin/env python3
"""Headless collector: keep ~/.cache/agent-usage/state.json current.

The GNOME Shell extension is pure presentation: it reads this file and draws.
Keeping the log parsing and the quota calls here means the shell process never
touches hundreds of megabytes of jsonl, and the numbers stay in the one place
they have been verified.

Writes are atomic (temp file + rename) so a reader never sees a half file.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fmt  # noqa: E402
import paths  # noqa: E402
import quota  # noqa: E402
import ring  # noqa: E402
import scan  # noqa: E402
import settings  # noqa: E402
from collector import Collector  # noqa: E402

STATE_PATH = os.path.join(paths.CACHE_DIR, "state.json")
# The extension touches this to ask for an immediate refresh; a watched file
# keeps the shell from having to spawn a process or send a signal.
TRIGGER_PATH = os.path.join(paths.CACHE_DIR, "refresh-request")
LOCAL_EVERY = 20
QUOTA_EVERY = 300  # used when the extension's settings cannot be read
# An explicit Refresh should mostly bypass the shared quota cache, but not so
# far that repeated clicking walks into the endpoint's rate limit.
FORCED_FRESH_S = 30

_running = True


def _stop(_sig, _frm):
    global _running
    _running = False


def _totals(side, key):
    t = side[key]["total"]
    total = scan.total_tokens(t)
    # tokens_h is pre-formatted here so the shell process never has to reproduce
    # the abbreviation rules and drift from what the CLI prints.
    return {
        "tokens": total,
        "tokens_h": fmt.fmt_tokens(total),
        "reqs": t["reqs"],
        **{f: t[f] for f in scan.FIELDS},
    }


def _models(side):
    ranked = sorted(side["today"]["by_model"].items(), key=lambda kv: -scan.total_tokens(kv[1]))
    return [
        {"name": fmt.short_model(m), "tokens": scan.total_tokens(t), "reqs": t["reqs"]}
        for m, t in ranked[:4]
    ]


def fetch_quota(providers, fresh_for=None, renew=False):
    """Readings for the given providers, never raising.

    An unexpected error escaping here would end the process, and the unit is
    Restart=always, so the daemon would respawn every RestartSec for as long as
    the cause lasted. The reason goes to the journal in full; the panel gets a
    short version that fits its one line.
    """
    out = {}
    for p in providers:
        kw = {"renew": renew}
        if fresh_for is not None:
            kw["fresh_for"] = fresh_for
        try:
            out[p.tag] = quota.fetch(p, **kw)
        except Exception as exc:
            sys.stderr.write("agent-usage: %s quota failed: %r\n" % (p.tag, exc))
            out[p.tag] = {"ok": False, "why": "error: " + type(exc).__name__}
    return out


def tool_state(provider, side, reading):
    raw_limits, live, why = quota.live_limits(reading)
    limits = [
        {
            # .get, not indexing: a cached limit may have been written by an
            # older build or come back short, and one missing field must not
            # cost the tool its whole block.
            "label": str(lim.get("label") or "?"),
            "percent": lim.get("percent") or 0,
            "severity": str(lim.get("severity") or "normal"),
            "colour": ring.severity_color(lim.get("percent"), lim.get("severity") or "normal"),
            "resets": fmt.fmt_reset(lim.get("resets_at")),
        }
        for lim in raw_limits
    ]
    session = next((lim for lim in limits if lim["label"].startswith("5-hour")), None)
    icon = ring.write_icon(
        paths.CACHE_DIR,
        session["percent"] if session else 0,
        session["severity"] if session else "normal",
        known=session is not None,
        tag=provider.tag,
        accent=provider.accent,
    )
    return {
        "id": provider.tag,
        "name": provider.name,
        "accent": provider.accent,
        "limits": limits,
        "live": live,
        "why": why,
        "icon": icon,
        # What the panel shows next to the ring: the 5-hour percent when we have
        # it, otherwise today's token volume, never a fabricated percentage.
        "badge": ("%d%%" % session["percent"]) if session else fmt.fmt_tokens(
            scan.total_tokens(side["today"]["total"])
        ),
        "badge_is_percent": session is not None,
        "stale": not live and bool(limits),
        "today": _totals(side, "today"),
        "week": _totals(side, "week"),
        "models": _models(side),
    }


_STARTING = {"ok": False, "why": "starting"}


def _safe_tool_state(provider, side, reading):
    """tool_state, or a tool with no bars when its reading cannot be read.

    A reading comes off disk and may have been written by a different build, or
    corrupted. Letting that escape would cost every tool its update, and the
    file is only rewritten on a later success, so the panel would stay frozen
    on the stale copy.
    """
    try:
        return tool_state(provider, side, reading)
    except Exception as exc:
        sys.stderr.write("agent-usage: %s reading unusable: %r\n" % (provider.tag, exc))
        return tool_state(provider, side, {"ok": False, "why": "reading unusable"})


def build_state(collector, readings, providers):
    local = collector.local(providers)
    return {
        "at": time.time(),
        "tools": [
            _safe_tool_state(p, local[p.tag], readings.get(p.tag, _STARTING))
            for p in providers
        ],
    }


def write_state(state):
    paths.ensure_cache_dir()
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh)
    os.replace(tmp, STATE_PATH)


def _trigger_stamp():
    """The trigger file's mtime, or None when it is not there.

    None rather than 0.0 so a deletion is not just another change of stamp.
    A forced pass renews tokens, which for Kimi means rotating a real refresh
    token and for Claude means running a prompt, so clearing the cache
    directory must not be enough to ask for one.
    """
    try:
        return os.path.getmtime(TRIGGER_PATH)
    except OSError:
        return None


def main():
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    collector = Collector()
    readings = {}
    last_quota = 0.0
    seen_trigger = _trigger_stamp()

    while _running:
        forced = False
        now = time.time()
        # Read every pass, so hiding a tool stops its scans and quota calls
        # within one LOCAL_EVERY. The extension hides it on screen at once.
        providers = settings.visible()
        tags = {p.tag for p in providers}
        # Drop the reading of a hidden tool, so showing it again fetches a
        # current one instead of drawing the old one as live.
        readings = {t: r for t, r in readings.items() if t in tags}
        if now - last_quota >= settings.quota_every(QUOTA_EVERY) or last_quota == 0.0:
            readings = fetch_quota(providers)
            last_quota = now
        else:
            # A tool shown again since the last check gets its reading now
            # rather than at the end of the interval.
            missing = [p for p in providers if p.tag not in readings]
            if missing:
                readings.update(fetch_quota(missing))
        try:
            write_state(build_state(collector, readings, providers))
        except Exception as exc:  # a bad pass must not kill the daemon
            sys.stderr.write("agent-usage: state write failed: %r\n" % (exc,))

        # Wake every second so SIGTERM lands promptly and a Refresh click is
        # picked up without waiting out the whole interval.
        for _ in range(LOCAL_EVERY):
            if not _running:
                break
            stamp = _trigger_stamp()
            if stamp is not None and (seen_trigger is None or stamp > seen_trigger):
                seen_trigger = stamp
                readings = fetch_quota(providers, FORCED_FRESH_S, renew=True)
                last_quota = time.time()
                forced = True
                break
            time.sleep(1)
        if forced:
            continue
    return 0


if __name__ == "__main__":
    sys.exit(main())
