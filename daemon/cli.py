#!/usr/bin/env python3
"""Print each agent's usage to the terminal, from the same data the panel uses."""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fmt  # noqa: E402
import quota  # noqa: E402
import ring  # noqa: E402
import scan  # noqa: E402
import settings  # noqa: E402
from collector import Collector  # noqa: E402

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"


def rgb(hex_colour):
    h = hex_colour.lstrip("#")
    return "\033[38;2;%d;%d;%dm" % (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


class Style:
    """ANSI codes, blanked when the output is not a terminal."""

    def __init__(self, enabled):
        self.on = enabled

    def __call__(self, code, text):
        return "%s%s%s" % (code, text, RESET) if self.on else str(text)


def colour_bar(st, percent, severity="normal", width=10):
    # A shaded empty cell, not a dimmed solid one: the output may be piped
    # somewhere that drops the ANSI codes, and a bar of ten identical blocks
    # would then say nothing at all.
    filled, empty = fmt.bar(percent, width, empty_char="░")
    return st(rgb(ring.severity_color(percent, severity)), filled) + st(DIM, empty)


def _quota_rows(st, reading):
    limits, live, why = quota.live_limits(reading)
    if not limits:
        print("   " + st(DIM, "quota unavailable (%s)" % (why or "unknown")))
        return
    if not live:
        print("   " + st(DIM, "quota unavailable (%s), showing last known" % why))
    for lim in limits:
        pct = lim["percent"] or 0
        reset = fmt.fmt_reset(lim["resets_at"])
        print(
            "   %-16s %s %s   %s"
            % (
                lim["label"],
                colour_bar(st, pct, lim["severity"]),
                st(rgb(ring.severity_color(pct, lim["severity"])), "%3d%%" % pct),
                st(DIM, "resets " + reset) if reset else "",
            )
        )
    if reading.get("extra_usage_enabled") and reading.get("extra_usage_percent") is not None:
        print("   %-16s %d%% extra usage" % ("", reading["extra_usage_percent"]))


def _local_rows(st, side):
    for label, key in (("Today", "today"), ("Last 7 days", "week")):
        t = side[key]["total"]
        print(
            "   %-16s %8s tokens   %6s req"
            % (label, fmt.fmt_tokens(scan.total_tokens(t)), fmt.fmt_count(t["reqs"]))
        )
    t = side["today"]["total"]
    if t["reqs"]:
        print("   " + st(DIM, "%-16s out %s · in %s · cache %s" % (
            "",
            fmt.fmt_tokens(t["out"]),
            fmt.fmt_tokens(t["inp"]),
            fmt.fmt_tokens(t["cache_read"] + t["cache_write"]),
        )))
    ranked = sorted(side["today"]["by_model"].items(), key=lambda kv: -scan.total_tokens(kv[1]))
    for model, tt in ranked[:4]:
        print("   " + st(DIM, "%-16s %8s tokens   %6s req" % (
            fmt.short_model(model)[:16],
            fmt.fmt_tokens(scan.total_tokens(tt)),
            fmt.fmt_count(tt["reqs"]),
        )))


def main(argv):
    as_json = "--json" in argv
    st = Style(sys.stdout.isatty() and not as_json)
    providers = settings.visible()
    local = Collector(providers).local(providers)
    readings = {p.tag: quota.fetch(p) for p in providers}
    if as_json:
        json.dump({"local": local, "quota": readings, "at": time.time()},
                  sys.stdout, indent=2, default=str)
        print()
        return 0
    if not providers:
        print("No coding agent to show: none is installed, or all are hidden in Preferences.")
        return 0
    print()
    for p in providers:
        print(st(BOLD + rgb(p.accent), " " + p.name))
        _quota_rows(st, readings[p.tag])
        _local_rows(st, local[p.tag])
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
