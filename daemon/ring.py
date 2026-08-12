#!/usr/bin/env python3
"""Ring gauge rendered as an SVG tray icon.

The arc tracks Claude's 5-hour window — the number that actually moves during a
working session — and takes its colour from that window's severity. A dual-ring
version was tried first and rejected: at the 16-22px the panel actually renders,
two concentric arcs smear into one blob. The weekly figure lives in the text
label instead, where it stays readable.

AppIndicator caches icons by name, so each distinct state gets its own filename;
stale files are swept on every write.
"""
from __future__ import annotations

import glob
import math
import os

SIZE = 22
# Bump when the drawing changes: the filename is the cache key, so without it a
# file written by an older build is reused and the new look never appears.
ICON_VERSION = 4
CENTER = SIZE / 2.0
RADIUS = 8.0
WIDTH = 3.5

TRACK = "#808080"
TRACK_OPACITY = 0.3

OK = "#34d399"  # green
WARN = "#fbbf24"  # amber
CRIT = "#f87171"  # red
UNKNOWN = "#8b90a0"

# Brand accents, used by the panel labels and popup headers.
CLAUDE = "#e08a6c"
KIMI = "#0ea5e9"

# Consumed percent -> colour, highest threshold first.
_TIERS = ((90, CRIT), (75, WARN), (0, OK))


def severity_color(percent, severity="normal"):
    """Colour for a consumed percentage.

    The provider's own severity can only make the reading worse, never better:
    it knows about caps we do not model, but a "normal" from it must not paint
    a 95%-consumed limit green.
    """
    p = max(0, min(100, int(percent or 0)))
    colour = next(c for threshold, c in _TIERS if p >= threshold)
    if severity == "critical":
        return CRIT
    if severity == "warning" and colour == OK:
        return WARN
    return colour


def ring_svg(percent, colour, known=True, accent=None):
    circumference = 2 * math.pi * RADIUS
    parts = [
        '<circle cx="%.2f" cy="%.2f" r="%.2f" fill="none" stroke="%s" '
        'stroke-width="%.2f" stroke-opacity="%.2f"/>'
        % (CENTER, CENTER, RADIUS, TRACK, WIDTH, TRACK_OPACITY)
    ]
    if not known:
        # Distinguish "no reading" from "0% used" — an empty track would
        # otherwise read as plenty of quota left. In the tool's own colour, so
        # the mark reads as that tool's badge and not as a dimmed gauge.
        parts.append(
            '<circle cx="%.2f" cy="%.2f" r="2.1" fill="%s"/>'
            % (CENTER, CENTER, accent or UNKNOWN)
        )
    else:
        pct = max(0.0, min(100.0, float(percent or 0)))
        if pct > 0:
            dash = circumference * pct / 100.0
            parts.append(
                '<circle cx="%.2f" cy="%.2f" r="%.2f" fill="none" stroke="%s" '
                'stroke-width="%.2f" stroke-dasharray="%.3f %.3f" stroke-linecap="round"/>'
                % (CENTER, CENTER, RADIUS, colour, WIDTH, dash, circumference - dash)
            )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'viewBox="0 0 %d %d"><g transform="rotate(-90 %.2f %.2f)">%s</g></svg>'
        % (SIZE, SIZE, SIZE, SIZE, CENTER, CENTER, "".join(parts))
    )


def write_icon(cache_dir, percent, severity="normal", known=True, tag="x", accent=None):
    """Render the gauge and return its path, or None if it could not be written.

    The path encodes the state because consumers cache icons by filename: the
    GNOME panel only reloads the image when the path it was handed changes.
    """
    icon_dir = os.path.join(cache_dir, "icons")
    state = "%03d-%s" % (int(percent or 0), severity[:4]) if known else "unknown"
    path = os.path.join(icon_dir, "ring%d-%s-%s.svg" % (ICON_VERSION, tag, state))
    try:
        os.makedirs(icon_dir, exist_ok=True)
        if not os.path.exists(path):
            tmp = path + ".tmp"
            with open(tmp, "w") as fh:
                fh.write(ring_svg(percent, severity_color(percent, severity), known, accent))
            os.replace(tmp, path)
        _sweep(icon_dir, path)
        return path
    except OSError:
        return None


def _sweep(icon_dir, keep, limit=8):
    """Only the newest icon per tool is ever displayed; keep a few, drop the rest."""
    files = sorted(
        glob.glob(os.path.join(icon_dir, "ring*.svg")), key=os.path.getmtime, reverse=True
    )
    for stale in files[limit:]:
        if stale != keep:
            try:
                os.unlink(stale)
            except OSError:
                pass


if __name__ == "__main__":  # visual check: python3 ring.py out.svg 92
    import sys

    dest = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ring.svg"
    pct = float(sys.argv[2]) if len(sys.argv) > 2 else 92
    with open(dest, "w") as fh:
        fh.write(ring_svg(pct, severity_color(pct)))
    print(dest)
