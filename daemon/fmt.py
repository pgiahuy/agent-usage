"""Formatting shared by the daemon (which pre-formats for the panel) and the CLI."""
from __future__ import annotations

from datetime import date, datetime


def fmt_tokens(n):
    if n >= 1_000_000_000:
        return "%.1fB" % (n / 1e9)
    if n >= 1_000_000:
        return "%.1fM" % (n / 1e6)
    if n >= 1_000:
        return "%.0fk" % (n / 1e3)
    return str(n)


def fmt_count(n):
    return "%.1fk" % (n / 1e3) if n >= 1000 else str(n)


def short_model(name):
    name = name.rsplit("/", 1)[-1]
    if name.startswith("claude-"):
        name = name[len("claude-"):]
    return name


def parse_iso(iso):
    """An ISO stamp as a datetime, or None when it is not one.

    A trailing Z becomes +00:00 first: fromisoformat only accepts Z from
    Python 3.11 and the collector supports 3.8. Providers differ on which they
    send, and one of them used to defend against this while the other did not,
    so the normalising lives here, where every stamp passes through.
    """
    if not isinstance(iso, str) or not iso:
        return None
    if iso.endswith("Z"):
        iso = iso[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None


def fmt_reset(iso):
    """ISO UTC -> local 'HH:MM' today, 'Fri 09:00' within the week, else 'Aug 18, 16:00'."""
    dt = parse_iso(iso)
    if dt is None:
        return ""
    dt = dt.astimezone()
    days = (dt.date() - date.today()).days
    if days == 0:
        return dt.strftime("%H:%M")
    if 0 < days < 7:
        return dt.strftime("%a %H:%M")
    return dt.strftime("%b %-d, %H:%M")


def bar(percent, width=10, empty_char="█"):
    """Filled and empty halves of a bar, as two strings the caller colours.

    The default empty character is the same solid block as the filled one, so a
    colour-capable surface reads like the ring gauge: a bright arc over a dim
    track. Callers that cannot rely on colour surviving (a terminal being piped
    to a file) should pass a visually distinct empty_char instead.

    Truncating rather than rounding keeps a full bar honest: only a true 100%
    fills every cell.
    """
    p = max(0, min(100, int(percent or 0)))
    filled = int(p * width / 100)
    if p > 0 and filled == 0:
        filled = 1  # any usage at all should be visible
    return "█" * filled, empty_char * (width - filled)
