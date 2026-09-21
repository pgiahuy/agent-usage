#!/usr/bin/env python3
"""Print Claude + Kimi usage to the terminal, from the same data the tray uses."""
from __future__ import annotations

import json
import sys

import ring
import usage_core as core

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
HEAD = "\033[38;2;120;180;255m"


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
    filled, empty = core.bar(percent, width, empty_char="░")
    return st(rgb(ring.severity_color(percent, severity)), filled) + st(DIM, empty)


def print_report(snap, st):
    local, quota = snap["local"], snap["quota"]

    print()
    print(st(BOLD + HEAD, " CLAUDE"))
    _quota_rows(st, quota["claude"])
    _local_rows(st, local["claude"])

    print()
    print(st(BOLD + HEAD, " KIMI"))
    _quota_rows(st, quota["kimi"])
    _local_rows(st, local["kimi"])
    print()


def _quota_rows(st, q):
    limits, live, why = core.live_limits(q)
    if not limits:
        print("   " + st(DIM, "quota unavailable (%s)" % (why or "unknown")))
        return
    if not live:
        print("   " + st(DIM, "quota unavailable (%s), showing last known" % why))
    for lim in limits:
        pct = lim["percent"] or 0
        reset = core.fmt_reset(lim["resets_at"])
        print(
            "   %-16s %s %s   %s"
            % (
                lim["label"],
                colour_bar(st, pct, lim["severity"]),
                st(rgb(ring.severity_color(pct, lim["severity"])), "%3d%%" % pct),
                st(DIM, "resets " + reset) if reset else "",
            )
        )
    if q.get("extra_usage_enabled") and q.get("extra_usage_percent") is not None:
        print("   %-16s %d%% extra usage" % ("", q["extra_usage_percent"]))


def _local_rows(st, side):
    for label, key in (("Today", "today"), ("Last 7 days", "week")):
        t = side[key]["total"]
        print(
            "   %-16s %8s tokens   %6s req"
            % (label, core.fmt_tokens(core.total_tokens(t)), core.fmt_count(t["reqs"]))
        )
    t = side["today"]["total"]
    if t["reqs"]:
        print(
            "   "
            + st(
                DIM,
                "%-16s out %s · in %s · cache %s"
                % (
                    "",
                    core.fmt_tokens(t["out"]),
                    core.fmt_tokens(t["inp"]),
                    core.fmt_tokens(t["cache_read"] + t["cache_write"]),
                ),
            )
        )
    by_model = side["today"]["by_model"]
    if by_model:
        ranked = sorted(by_model.items(), key=lambda kv: -core.total_tokens(kv[1]))
        for model, tt in ranked[:4]:
            print(
                "   "
                + st(
                    DIM,
                    "%-16s %8s tokens   %6s req"
                    % (
                        core.short_model(model)[:16],
                        core.fmt_tokens(core.total_tokens(tt)),
                        core.fmt_count(tt["reqs"]),
                    ),
                )
            )


def main(argv):
    as_json = "--json" in argv
    st = Style(sys.stdout.isatty() and not as_json)
    snap = core.Collector().snapshot()
    if as_json:
        json.dump(snap, sys.stdout, indent=2, default=str)
        print()
    else:
        print_report(snap, st)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
