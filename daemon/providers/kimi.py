"""Kimi Code.

Tokens: ~/.kimi-code/sessions/*/*/agents/*/wire.jsonl, usage.record lines.
Quota: GET https://api.kimi.com/coding/v1/usages, which Kimi does not
document, so the path is found by asking (see _probe). The OAuth token in
~/.kimi-code/credentials/kimi-code.json lives 15 minutes.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
from datetime import datetime

import cache
import fmt
import net
import paths
import quota
from providers.base import Provider

HOME = paths.tool_home("KIMI_CODE_HOME", ".kimi-code")
LOG_GLOB = os.path.join(HOME, "sessions", "*", "*", "agents", "*", "wire.jsonl")
CREDS = os.path.join(HOME, "credentials", "kimi-code.json")
# kimi serialises its own refreshes with proper-lockfile on this target, which
# means a mkdir of "<target>.lock"; taking the same lock is what keeps the two
# of us from both spending one rotating refresh token.
REFRESH_LOCK = os.path.join(HOME, "oauth", "kimi-code") + ".lock"

# The same overrides kimi itself honours, and the client id it signs in with.
OAUTH_HOST = (os.environ.get("KIMI_CODE_OAUTH_HOST") or os.environ.get("KIMI_OAUTH_HOST")
              or "https://auth.kimi.com").rstrip("/")
CLIENT_ID = "17e5f671-d194-4dfb-9706-5516cb48c098"

API_BASE = "https://api.kimi.com"
# Kimi Code documents no usage endpoint, so the working one has to be found by
# asking. The path that answers with percentages is remembered and used alone
# afterwards; a sweep that finds nothing is remembered too, so seven requests do
# not go out every five minutes forever.
_PATHS = (
    "/coding/v1/usages",
    "/coding/v1/usage",
    "/coding/v1/me",
    "/coding/v1/quota",
    "/coding/v1/quotas",
    "/coding/v1/subscription",
    "/coding/v1/limits",
)
_RESWEEP_S = 86400
# What kimi-raw.json keeps of the reply; the rest carries account and billing ids.
_RAW_KEEP = frozenset({"usage", "usages", "limits"})


def extract(raw):
    if b'"usage.record"' not in raw:
        return None
    try:
        d = json.loads(raw)
    except ValueError:
        return None
    # Scope "session" is a running total; adding it would double-count.
    if d.get("type") != "usage.record" or d.get("usageScope") != "turn":
        return None
    u = d.get("usage") or {}
    ms = d.get("time")
    if not ms:
        return None
    inp = int(u.get("inputOther") or 0)
    out = int(u.get("output") or 0)
    cread = int(u.get("inputCacheRead") or 0)
    cwrite = int(u.get("inputCacheCreation") or 0)
    return (
        ms / 1000.0,
        d.get("model") or "unknown",
        "%d|%d|%d|%d" % (ms, inp, out, cread),
        inp,
        out,
        cread,
        cwrite,
    )


def token():
    return quota.read_token(CREDS, "access_token", "expires_at", "s")


# --------------------------------------------------------------------------
# Reading the usage reply
# --------------------------------------------------------------------------

_PCT_KEYS = ("percent", "percentage", "utilization", "utilisation",
             "usage_percent", "used_percent", "usedPercent")
_USED_KEYS = ("used", "usage", "consumed", "current", "spent")
_CAP_KEYS = ("limit", "total", "quota", "max", "cap", "allowance")
_RESET_KEYS = ("resets_at", "resetAt", "reset_at", "reset_time", "resetTime",
               "refresh_at", "next_reset", "nextReset", "period_end", "periodEnd")
_NAME_KEYS = ("label", "name", "kind", "type", "window", "period", "scope", "id")
_TIME_UNIT_MIN = {"minute": 1, "hour": 60, "day": 1440, "week": 10080}


def _num(node, keys):
    """First of `keys` that holds a number, including one written as a string.

    Kimi sends every quota figure as a string ("limit": "100"), which is why an
    is-a-number test alone finds nothing in its payload.
    """
    for k in keys:
        v = node.get(k)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v.strip())
            except ValueError:
                continue
    return None


def _pct_used(node):
    """Consumed percentage from a {limit, used|remaining} object."""
    limit = _num(node, _CAP_KEYS)
    used = _num(node, _USED_KEYS)
    if used is None:
        rest = _num(node, ("remaining", "left", "available"))
        if rest is not None and limit:
            used = limit - rest
    if used is None or not limit:
        return None
    return max(0, min(100, round(used / limit * 100)))


def _window_label(window):
    """{'duration': 300, 'timeUnit': 'TIME_UNIT_MINUTE'} -> '5-hour'."""
    n = _num(window, ("duration", "length", "size"))
    unit = str(window.get("timeUnit") or window.get("unit") or "")
    mins = _TIME_UNIT_MIN.get(unit.replace("TIME_UNIT_", "").lower())
    if n is None or not mins:
        return "Window"
    total = int(n) * mins
    if total % 10080 == 0:
        return "Weekly" if total == 10080 else "%d-week" % (total // 10080)
    if total % 1440 == 0:
        return "Daily" if total == 1440 else "%d-day" % (total // 1440)
    if total % 60 == 0:
        return "%d-hour" % (total // 60)
    return "%d-min" % total


def _to_iso(v):
    """Reset stamps arrive as ISO, epoch seconds or epoch milliseconds."""
    if isinstance(v, str):
        dt = fmt.parse_iso(v)
        return dt.isoformat() if dt else v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        secs = v / 1000.0 if v > 1e11 else float(v)
        try:
            return datetime.fromtimestamp(secs).astimezone().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _row(label, node, percent=None):
    """One bar, or None when the object carries no usable percentage."""
    pct = _pct_used(node) if percent is None else percent
    if pct is None:
        return None
    resets = next((_to_iso(node[k]) for k in _RESET_KEYS if node.get(k) is not None), None)
    return {
        "label": label[:12],
        "percent": pct,
        "severity": str(node.get("severity") or "normal"),
        "resets_at": resets,
        "is_active": True,
    }


def _as_limit(node):
    """Fallback for a shape we have not seen: only trust an outright percentage
    or a stated used/limit pair, never a lone number near a promising word."""
    if not isinstance(node, dict):
        return None
    pct = _num(node, _PCT_KEYS)
    pct = max(0, min(100, round(pct))) if pct is not None else None
    label = next((str(node[k]) for k in _NAME_KEYS if isinstance(node.get(k), str)), "Usage")
    return _row(label, node, pct)


def parse_limits(data):
    """Quota bars from /coding/v1/usages.

    Its real shape, as returned on 2026-08-13:
        usage:  {limit, used, remaining, resetTime}       the purchased plan
        limits: [{window: {duration, timeUnit},
                  detail: {limit, remaining, resetTime}}] the rolling windows
    Everything numeric arrives as a string, and the rolling windows report what
    is left rather than what was spent.
    """
    if not isinstance(data, dict):
        return [r for r in (_as_limit(x) for x in data) if r] if isinstance(data, list) else []

    rows = []
    for entry in data.get("limits") or []:
        if not isinstance(entry, dict):
            continue
        detail = entry.get("detail") if isinstance(entry.get("detail"), dict) else entry
        row = _row(_window_label(entry.get("window") or {}), detail)
        if row:
            rows.append(row)
    # The plan itself has no window attached, so it is named for what it is.
    plan = data.get("usage")
    if isinstance(plan, dict):
        row = _row("Plan", plan)
        if row:
            rows.append(row)
    if rows:
        return rows

    for key in ("usages", "quotas", "windows", "data", "result"):
        inner = data.get(key)
        if isinstance(inner, list):
            rows = [r for r in (_as_limit(x) for x in inner) if r]
            if rows:
                return rows
        elif isinstance(inner, dict):
            rows = parse_limits(inner)
            if rows:
                return rows
    one = _as_limit(data)
    return [one] if one else []


# --------------------------------------------------------------------------
# Asking for it
# --------------------------------------------------------------------------


# How long a whole endpoint sweep may take, however many candidates are left.
_PROBE_BUDGET_S = 20.0


def _probe(tok, timeout):
    """Sweep the candidate paths for one that reports usage, as (path, payload, rows).

    A path that answers 200 but carries no percentages does not win the sweep,
    it only becomes the fallback: /me answers for every signed-in user, so
    stopping at the first 200 would cache it as the endpoint and the real one
    would never be tried. A 401/403/429 is about the caller rather than the
    path, so it stops the sweep and is reported; anything else means keep
    looking.
    """
    known = cache.read("kimi-endpoint.json") or {}
    if known.get("path"):
        candidates = [known["path"]] + [p for p in _PATHS if p != known["path"]]
    elif time.time() - known.get("swept_at", 0) < _RESWEEP_S:
        return None, None, []  # a full sweep came up empty recently
    else:
        candidates = list(_PATHS)

    fallback = (None, None)
    # One budget for the sweep, not one timeout per candidate: seven of those
    # back to back would hold the daemon's only thread long enough to stall
    # the SIGTERM check and the refresh trigger with it.
    deadline = time.monotonic() + min(_PROBE_BUDGET_S, timeout * 2)
    for path in candidates:
        left = deadline - time.monotonic()
        if left <= 0.5:
            break
        try:
            data = net.get_json(API_BASE + path, tok, min(timeout, left))
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 429):
                raise
            net.discard(exc)
            continue
        rows = parse_limits(data)
        if rows:
            cache.write("kimi-endpoint.json", {"path": path, "found_at": time.time()})
            return path, data, rows
        if fallback[0] is None:
            fallback = (path, data)
    cache.write("kimi-endpoint.json", {"path": None, "swept_at": time.time()})
    return fallback[0], fallback[1], []


def fetch(tok, timeout):
    path, data, limits = _probe(tok, timeout)
    if path is None:
        raise quota.Unavailable("no usage endpoint")

    # Keep the usage part of the real reply, the only record of what the API
    # actually sends. The rest (account and subscription ids, the top-up wallet)
    # is not ours to keep, so only its key names are recorded.
    if isinstance(data, dict):
        kept = {k: v for k, v in data.items() if k in _RAW_KEEP}
        dropped = sorted(set(data) - _RAW_KEEP)
    else:
        kept, dropped = data, []
    cache.write("kimi-raw.json", {"path": path, "at": time.time(), "data": kept,
                                  "dropped_keys": dropped})

    if not limits:
        raise quota.Unavailable("no percentages at %s" % path.rsplit("/", 1)[-1])
    return {"path": path, "limits": limits}


# --------------------------------------------------------------------------
# Renewing the token
# --------------------------------------------------------------------------


def _kimi_running():
    """True when any kimi process is up.

    Every argument is checked, not just argv[0]: a native binary puts its own
    path there, but a node or shell wrapped install puts the interpreter
    there and kimi further along. Missing that would quietly drop the first of
    the three things that keep a refresh from racing kimi's own. The resolved
    executable is checked too, which catches a wrapper that renames itself.
    """
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as fh:
                argv = fh.read().split(b"\0")
        except OSError:
            continue
        if any(os.path.basename(a) == b"kimi" for a in argv if a):
            return True
        try:
            exe = os.readlink("/proc/%s/exe" % pid)
        except OSError:
            continue
        if os.path.basename(exe) == "kimi" or exe.startswith(HOME + os.sep):
            return True
    return False


# What a refresh replaces. Everything else in the file is kimi's to own.
_TOKEN_FIELDS = ("access_token", "refresh_token", "expires_in", "expires_at",
                 "scope", "token_type")


def _write_private_json(path, obj):
    """Write obj to path atomically, and private to this user for certain.

    O_CREAT's mode argument applies only when open() creates the file, so
    residue from an earlier crashed run at a laxer mode kept that mode and the
    fresh refresh token landed in it. O_EXCL makes creation the only
    possibility, which also means open() cannot be aimed through a symlink
    someone left at the temp path. fchmod then states the mode outright
    instead of leaving it to the umask.
    """
    tmp = path + ".agent-usage.tmp"
    try:
        os.unlink(tmp)
    except OSError:
        pass
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(obj, fh)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        # Leaving the temp file behind would make the next run take the
        # pre-existing path again, which is the hole this closes.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, path)


# proper-lockfile abandons a lock untouched for 5s. Re-stamping every 2s keeps
# a held lock held, which the request timeout alone cannot promise: it governs
# connect and recv, not getaddrinfo, so one slow name lookup is enough to go
# over. The library keeps its own locks alive the same way.
_LOCK_STALE_S = 5.0
_LOCK_REFRESH_S = 2.0


class _LockKeeper:
    """Keep a held lock's mtime fresh for as long as it is held."""

    def __init__(self, path):
        self.path = path
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def _run(self):
        while not self._stop.wait(_LOCK_REFRESH_S):
            try:
                os.utime(self.path, None)
            except OSError:
                return  # taken from us, or gone: the caller checks before writing

    def __exit__(self, *_exc):
        self._stop.set()
        self._thread.join(timeout=_LOCK_STALE_S)


def _lock_identity(path):
    """(dev, ino) of the lock we hold, or None when it is gone.

    A lock that was stolen and recreated is a different directory at the same
    path, so comparing identity is what tells our lock from its replacement.
    """
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino)


def renew(timeout=4):
    """Refresh Kimi's token the way kimi itself does, under kimi's own lock.

    The refresh token rotates, so a refresh racing kimi's would leave one side
    holding a dead token and the user signed out. Hence: never while a kimi
    process is running, never without the lock, and a lock that is held is
    waited for by nobody: kimi stamps its lock every few seconds, and if it is
    there, kimi is refreshing and will write the result itself.
    """
    if not OAUTH_HOST.startswith("https://"):
        return "oauth host is not https"
    if _kimi_running():
        return "kimi is running"
    try:
        os.makedirs(os.path.dirname(REFRESH_LOCK), exist_ok=True)
        os.mkdir(REFRESH_LOCK)
    except FileExistsError:
        return "kimi is refreshing"
    except OSError as exc:
        return net.why(exc)
    held = _lock_identity(REFRESH_LOCK)
    try:
        with _LockKeeper(REFRESH_LOCK):
            return _renew_locked(held, timeout)
    finally:
        # Only ours. A lock that was taken from us belongs to whoever has it
        # now, and removing it would hand the credentials to two writers.
        if _lock_identity(REFRESH_LOCK) == held:
            try:
                os.rmdir(REFRESH_LOCK)
            except OSError:
                pass


def _renew_locked(held, timeout):
    """The refresh itself, with the lock held and kept alive by the caller."""
    try:
        with open(CREDS) as fh:
            creds = json.load(fh)
    except (OSError, ValueError):
        return "not signed in"
    if token()[0]:
        return None  # renewed meanwhile, by kimi
    refresh = creds.get("refresh_token")
    if not refresh:
        return "no refresh token"
    try:
        data = net.post_form(OAUTH_HOST + "/api/oauth/token", {
            "client_id": CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": refresh,
        }, timeout)
    except urllib.error.HTTPError as exc:
        net.discard(exc)
        return "refresh HTTP %d" % exc.code
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
        return net.why(exc)
    access = data.get("access_token")
    expires_in = data.get("expires_in")
    if not access or not isinstance(expires_in, (int, float)):
        return "bad refresh reply"
    creds.update(
        access_token=access,
        refresh_token=data.get("refresh_token") or refresh,
        expires_in=expires_in,
        expires_at=int(time.time() + expires_in),
    )
    for key in ("scope", "token_type"):
        if data.get(key):
            creds[key] = data[key]
    if _lock_identity(REFRESH_LOCK) != held:
        # The lock was taken from us while the request was out, so another
        # refresh may already have written a newer pair. Ours is newer at
        # the server, but writing it blind could undo theirs, and we no
        # longer hold the right to write at all.
        return "lost the refresh lock"
    # Re-read under the lock: anything kimi wrote to the other fields while
    # the request was out is kept, and only the token fields are replaced.
    try:
        with open(CREDS) as fh:
            latest = json.load(fh)
        if isinstance(latest, dict):
            latest.update({k: creds[k] for k in _TOKEN_FIELDS if k in creds})
            creds = latest
    except (OSError, ValueError):
        pass
    try:
        _write_private_json(CREDS, creds)
    except OSError as exc:
        return net.why(exc)
    return None


PROVIDER = Provider(
    tag="kimi",
    name="KIMI",
    accent="#0ea5e9",
    home=HOME,
    log_glob=LOG_GLOB,
    extract=extract,
    token=token,
    fetch=fetch,
    renew=renew,
)
