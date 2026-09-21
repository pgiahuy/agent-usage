#!/usr/bin/env python3
"""Menu content for the AppIndicator fallback: [(pango_markup, indent), ...].

Superseded by the GNOME Shell extension, which can actually draw. This path
survives only as a stopgap, and it carries a hard constraint: GNOME serialises
AppIndicator menus over DBusMenu, which transports plain text. Every span,
weight and monospace hint below is stripped before it reaches the panel, so
nothing here may depend on colour to be readable.
"""
from __future__ import annotations

import ring
import usage_core as core

DIM = "#8b8b8b"
LABEL_W = 15  # width of the leading name column, in monospace cells

# The unfilled part of a bar is the same block as the filled part, faded: the
# same track-plus-arc reading as the ring icon. Matches ring.TRACK_OPACITY.
TRACK_ALPHA = "38%"


def esc(text):
    return (
        str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def coloured(markup, colour):
    return '<span foreground="%s">%s</span>' % (colour, markup)


def tool_limits(quota, tool="claude"):
    """Live limits, or the last known set when the API is unreachable."""
    limits, live, _why = core.live_limits(quota.get(tool, {}))
    return limits, live


def session_limit(quota):
    limits, live = tool_limits(quota)
    return next((l for l in limits if l["label"].startswith("5-hour")), None), live


def _quota_rows(quota, tool):
    rows = []
    limits, live = tool_limits(quota, tool)
    q = quota.get(tool, {})
    if not limits:
        return [
            (coloured("<i>quota unavailable (%s)</i>" % esc(q.get("why") or "unknown"), DIM), 1)
        ]
    if not live:
        rows.append(
            (coloured("<i>quota unavailable (%s), showing last known</i>" % esc(q.get("why")), DIM), 1)
        )
    for lim in limits:
        pct = lim["percent"] or 0
        colour = ring.severity_color(pct, lim["severity"])
        # Shaded empty cells, not colour-dimmed solid ones: DBusMenu drops the
        # colour, and a bar of ten identical blocks would read as 100% at 0%.
        filled, empty = core.bar(pct, empty_char="░")
        reset = core.fmt_reset(lim["resets_at"])
        rows.append(
            (
                "<tt>%s</tt>%s%s<tt> %s</tt>%s"
                % (
                    esc(lim["label"]).ljust(LABEL_W),
                    coloured("<tt>%s</tt>" % filled, colour),
                    '<span foreground="%s" alpha="%s"><tt>%s</tt></span>'
                    % (DIM, TRACK_ALPHA, empty),
                    coloured("<b>%3d%%</b>" % pct, colour),
                    coloured("  <small>resets %s</small>" % esc(reset), DIM) if reset else "",
                ),
                1,
            )
        )
    if q.get("extra_usage_enabled") and q.get("extra_usage_percent") is not None:
        rows.append(("<tt>%s%d%% extra usage</tt>" % (" " * LABEL_W, q["extra_usage_percent"]), 1))
    return rows


def _local_rows(side):
    rows = []
    for label, key in (("Today", "today"), ("Last 7 days", "week")):
        t = side[key]["total"]
        rows.append(
            (
                "<tt>%s%8s tokens   %6s req</tt>"
                % (
                    label.ljust(LABEL_W),
                    core.fmt_tokens(core.total_tokens(t)),
                    core.fmt_count(t["reqs"]),
                ),
                1,
            )
        )
    t = side["today"]["total"]
    if t["reqs"]:
        rows.append(
            (
                coloured(
                    "<small><tt>%sout %s · in %s · cache %s</tt></small>"
                    % (
                        " " * LABEL_W,
                        core.fmt_tokens(t["out"]),
                        core.fmt_tokens(t["inp"]),
                        core.fmt_tokens(t["cache_read"] + t["cache_write"]),
                    ),
                    DIM,
                ),
                1,
            )
        )
    ranked = sorted(side["today"]["by_model"].items(), key=lambda kv: -core.total_tokens(kv[1]))
    for model, tt in ranked[:4]:
        rows.append(
            (
                coloured(
                    "<small><tt>%s%8s tokens   %6s req</tt></small>"
                    % (
                        esc(core.short_model(model))[:LABEL_W].ljust(LABEL_W),
                        core.fmt_tokens(core.total_tokens(tt)),
                        core.fmt_count(tt["reqs"]),
                    ),
                    DIM,
                ),
                1,
            )
        )
    return rows


def build(local, quota):
    """Full menu body, in order. A None row marks a separator."""
    rows = [("<b>CLAUDE</b>", 0)]
    rows += _quota_rows(quota, "claude")
    rows += _local_rows(local["claude"])
    rows.append(None)
    rows.append(("<b>KIMI</b>", 0))
    rows += _quota_rows(quota, "kimi")
    rows += _local_rows(local["kimi"])
    return rows


def panel_label(local, quota):
    parts = []
    session, live = session_limit(quota)
    limits, _ = tool_limits(quota)
    if session:
        parts.append("%d%%%s" % (session["percent"] or 0, "" if live else "?"))
        week = next((l for l in limits if l["label"] == "Weekly"), None)
        if week and (week["percent"] or 0) >= 50:
            parts.append("wk %d%%" % week["percent"])
    else:
        parts.append("C " + core.fmt_tokens(core.total_tokens(local["claude"]["today"]["total"])))
    parts.append("K " + core.fmt_tokens(core.total_tokens(local["kimi"]["today"]["total"])))
    return " · ".join(parts)
