"""Plan usage from each provider's own API, the same way for every provider.

The flow is shared and only the request itself is the provider's: serve a
fresh cached reading, else read the token the agent wrote when it signed in,
renew it on an explicit Refresh, respect a 429 backoff, ask, and cache what
came back. A failure never raises; it returns the reason and the last known
reading, which live_limits() decides how much of to keep showing.
"""
from __future__ import annotations

import json
import time
import urllib.error
from datetime import datetime

import cache
import net


class Unavailable(Exception):
    """The provider answered but gave no reading; str() is the reason shown."""


def read_token(path, key, exp_key, exp_unit, node=None):
    """(access token, None) while it is valid, else (None, reason).

    exp_unit is "s" or "ms", for how the file writes its expiry; node names the
    object the token sits in, when it is not at the top level.
    """
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None, "not signed in"
    if node is not None:
        data = data.get(node) or {}
    tok = data.get(key)
    exp = data.get(exp_key)
    if not tok:
        return None, "no token"
    if exp:
        exp_s = exp / 1000.0 if exp_unit == "ms" else float(exp)
        if exp_s <= time.time() + 30:
            return None, "token expired"
    return tok, None


def fetch(provider, timeout=8, fresh_for=cache.FRESH_S, renew=False):
    """One provider's reading, as a dict with "ok" and either "limits" or "why".

    renew=True lets an expired token be renewed first; only an explicit Refresh
    asks for that, never the timed loop.
    """
    reading_name = "%s-quota.json" % provider.tag
    backoff_name = "%s-backoff.json" % provider.tag
    cached = cache.read_versioned(reading_name)
    if cached and time.time() - cached.get("fetched_at", 0) < fresh_for:
        return dict(cached, from_cache=True)

    tok, why = provider.token()
    if tok is None and renew and why == "token expired":
        failed = provider.renew()
        tok, why = provider.token()
        why = failed or why
    if tok is None:
        return {"ok": False, "why": why, "cached": cached}

    wait = cache.backoff_until(backoff_name) - time.time()
    if wait > 0:
        return {"ok": False, "why": "rate limited, retrying in %ds" % wait, "cached": cached}
    try:
        reading = provider.fetch(tok, timeout)
    except urllib.error.HTTPError as exc:
        net.discard(exc)
        if exc.code == 429:
            wait = cache.backoff_bump(backoff_name)
            return {"ok": False, "why": "rate limited, retrying in %ds" % wait, "cached": cached}
        return {"ok": False, "why": "HTTP %d" % exc.code, "cached": cached}
    except Unavailable as exc:
        cache.backoff_clear(backoff_name)
        return {"ok": False, "why": str(exc), "cached": cached}
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
        return {"ok": False, "why": net.why(exc), "cached": cached}
    cache.backoff_clear(backoff_name)

    out = {"ok": True, "v": cache.VERSION, "fetched_at": time.time()}
    out.update(reading)
    cache.write(reading_name, out)
    return out


def reset_passed(iso, now=None):
    """True once a reset stamp has gone by.

    A stamp with no timezone is read as local, the same way fmt_reset reads it.
    """
    if not isinstance(iso, str) or not iso:
        return False
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.timestamp() <= (time.time() if now is None else now)


def live_limits(reading):
    """(limits, live, why) for one provider's reading.

    A cached reading outlives the window it measured. Once its reset time has
    gone by the window has rolled over, so the old percentage describes a
    period that no longer exists and is dropped. Dropped rather than zeroed:
    what the new window holds is unknown until a fetch succeeds, and this tool
    does not show a number it has not been told.
    """
    if reading.get("ok"):
        return reading.get("limits") or [], True, None
    cached = (reading.get("cached") or {}).get("limits") or []
    kept = [
        lim
        for lim in cached
        if isinstance(lim, dict) and not reset_passed(lim.get("resets_at"))
    ]
    return kept, False, reading.get("why")
