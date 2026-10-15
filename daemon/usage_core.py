#!/usr/bin/env python3
"""Collect Claude Code and Kimi Code usage.

Two sources:
  - Local logs, for tokens actually spent, bucketed by day and by model:
      Claude  ~/.claude/projects/**/*.jsonl                  (type=assistant -> message.usage)
      Kimi    ~/.kimi-code/sessions/*/*/agents/*/wire.jsonl  (type=usage.record, scope=turn)
  - Provider quota APIs, for percent of plan consumed and reset times:
      Claude  GET https://api.anthropic.com/api/oauth/usage  (the endpoint /usage itself calls)
      Kimi    GET https://api.kimi.com/coding/v1/…           (path discovered, see _kimi_probe)

The scanner keeps byte offsets in memory, so the first sweep costs about a
second and every later one is effectively free. Nothing is cached to disk, so
the numbers can never drift out of sync with a stale cache file.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

HOME = os.path.expanduser("~")


def _tool_home(env_var, default_name):
    """Where a tool keeps its data. Neither location is ours to assume: Claude
    Code moves with CLAUDE_CONFIG_DIR and Kimi Code with KIMI_CODE_HOME, and a
    user who has set either would otherwise just see an empty panel."""
    override = os.environ.get(env_var)
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return os.path.join(HOME, default_name)


CLAUDE_HOME = _tool_home("CLAUDE_CONFIG_DIR", ".claude")
KIMI_HOME = _tool_home("KIMI_CODE_HOME", ".kimi-code")

CLAUDE_GLOB = os.path.join(CLAUDE_HOME, "projects", "**", "*.jsonl")
CLAUDE_CREDS = os.path.join(CLAUDE_HOME, ".credentials.json")
KIMI_GLOB = os.path.join(KIMI_HOME, "sessions", "*", "*", "agents", "*", "wire.jsonl")
KIMI_CREDS = os.path.join(KIMI_HOME, "credentials", "kimi-code.json")
# kimi serialises its own refreshes with proper-lockfile on this target, which
# means a mkdir of "<target>.lock"; taking the same lock is what keeps the two
# of us from both spending one rotating refresh token.
KIMI_REFRESH_LOCK = os.path.join(KIMI_HOME, "oauth", "kimi-code") + ".lock"

CACHE_DIR = os.path.join(
    os.environ.get("XDG_CACHE_HOME", os.path.join(HOME, ".cache")), "agent-usage"
)

# Only the last 7 days are ever reported; the extra day absorbs timezone skew.
WINDOW_DAYS = 8

FIELDS = ("inp", "out", "cache_read", "cache_write")


def _zero():
    return {"inp": 0, "out": 0, "cache_read": 0, "cache_write": 0, "reqs": 0}


def _add(dst, inp, out, cread, cwrite):
    dst["inp"] += inp
    dst["out"] += out
    dst["cache_read"] += cread
    dst["cache_write"] += cwrite
    dst["reqs"] += 1


def total_tokens(t):
    return t["inp"] + t["out"] + t["cache_read"] + t["cache_write"]


# --------------------------------------------------------------------------
# One log line -> (epoch, model, dedup_key, inp, out, cache_read, cache_write)
# --------------------------------------------------------------------------


def _claude_extract(raw):
    if b'"usage"' not in raw:
        return None
    try:
        d = json.loads(raw)
    except ValueError:
        return None
    if d.get("type") != "assistant":
        return None
    msg = d.get("message") or {}
    u = msg.get("usage")
    if not isinstance(u, dict):
        return None
    model = msg.get("model") or "unknown"
    if model.startswith("<"):  # <synthetic>
        return None
    ts = d.get("timestamp")
    if not ts:
        return None
    try:
        epoch = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
    mid, rid = msg.get("id"), d.get("requestId")
    key = "%s|%s" % (mid or "", rid or "") if (mid or rid) else None
    return (
        epoch,
        model,
        key,
        int(u.get("input_tokens") or 0),
        int(u.get("output_tokens") or 0),
        int(u.get("cache_read_input_tokens") or 0),
        int(u.get("cache_creation_input_tokens") or 0),
    )


def _kimi_extract(raw):
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


# --------------------------------------------------------------------------


def _recent(path, cutoff):
    try:
        return os.path.getmtime(path) >= cutoff
    except OSError:
        return False


class Scanner:
    """Incrementally scan append-only jsonl logs into per-day, per-model totals."""

    def __init__(self, pattern, extract):
        self.pattern = pattern
        self.extract = extract
        self.offsets = {}  # path -> bytes already consumed
        self.seen = {}  # day -> set of dedup keys (resume/fork replays old history)
        self.days = {}  # 'YYYY-MM-DD' -> model -> totals

    def scan(self):
        cutoff = time.time() - WINDOW_DAYS * 86400
        for path in glob.iglob(self.pattern, recursive=True):
            try:
                st = os.stat(path)
            except OSError:
                continue
            # An mtime older than the window means every record inside is older too.
            if st.st_mtime < cutoff:
                continue
            off = self.offsets.get(path, 0)
            if st.st_size < off:  # truncated or rewritten -> start over
                off = 0
            if st.st_size == off:
                continue
            try:
                self._read(path, off, cutoff)
            except OSError:
                continue
        self._prune(cutoff)
        return self.days

    def _read(self, path, off, cutoff):
        with open(path, "rb") as fh:
            fh.seek(off)
            pos = off
            for raw in fh:
                if not raw.endswith(b"\n"):
                    break  # half-written line; pick it up next sweep
                pos += len(raw)
                rec = self.extract(raw)
                if rec is None:
                    continue
                epoch, model, key, inp, out, cread, cwrite = rec
                if epoch < cutoff:
                    continue
                day = date.fromtimestamp(epoch).isoformat()
                if key is not None:
                    # Duplicates carry the same timestamp, hence the same day, so
                    # bucketing the dedup set by day still catches every repeat
                    # while letting old keys age out.
                    bucket = self.seen.setdefault(day, set())
                    if key in bucket:
                        continue
                    bucket.add(key)
                _add(
                    self.days.setdefault(day, {}).setdefault(model, _zero()),
                    inp,
                    out,
                    cread,
                    cwrite,
                )
            self.offsets[path] = pos

    def _prune(self, cutoff):
        keep = date.fromtimestamp(cutoff).isoformat()
        for day in [d for d in self.days if d < keep]:
            del self.days[day]
        for day in [d for d in self.seen if d < keep]:
            del self.seen[day]
        # Files that fell out of the window are never read again; drop their offsets.
        for path in [p for p in self.offsets if not _recent(p, cutoff)]:
            del self.offsets[path]


def summarize(days):
    """days -> {'today': {...}, 'week': {...}} with totals and a per-model split."""
    today = date.today()
    week_start = (today - timedelta(days=6)).isoformat()
    today_s = today.isoformat()

    out = {}
    for label, keep in (("today", lambda d: d == today_s), ("week", lambda d: d >= week_start)):
        total = _zero()
        by_model = {}
        for day, models in days.items():
            if not keep(day):
                continue
            for model, t in models.items():
                acc = by_model.setdefault(model, _zero())
                for f in FIELDS:
                    acc[f] += t[f]
                    total[f] += t[f]
                acc["reqs"] += t["reqs"]
                total["reqs"] += t["reqs"]
        out[label] = {"total": total, "by_model": by_model}
    return out


# --------------------------------------------------------------------------
# Provider quota
# --------------------------------------------------------------------------

_CLAUDE_LABELS = {"session": "5-hour", "weekly_all": "Weekly"}

# The per-model weekly cap ("weekly_scoped"). Dropped on request: it is a third
# bar that mostly tracks the plain weekly one, and its model name never fit the
# panel's name column.
_CLAUDE_SKIP_KINDS = {"weekly_scoped"}

# Bump when the cached payload's shape or labels change, so readings written by
# an older build are discarded instead of surfacing with stale wording.
QUOTA_CACHE_VERSION = 5

# The tray and the CLI share one on-disk reading. A cached value younger than
# this is served without touching the network, which keeps two processes from
# each spending their own request against a rate-limited endpoint.
QUOTA_FRESH_S = 120

_BACKOFF_MIN, _BACKOFF_MAX = 60.0, 900.0


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Turn every redirect into an HTTPError instead of following it.

    urllib copies the Authorization header onto the redirected request, to any
    host and even from https down to http, so following one would hand the
    bearer token to wherever the Location points.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _get_json(url, token, timeout, extra_headers=None):
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
        "User-Agent": "agent-usage-indicator/1.0",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    with _OPENER.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ensure_cache_dir():
    """Create the cache directory private to the user, and make it so if an
    older build left it group-writable: it holds quota readings and Kimi's raw
    usage reply."""
    os.makedirs(CACHE_DIR, mode=0o700, exist_ok=True)
    if os.stat(CACHE_DIR).st_mode & 0o077:
        os.chmod(CACHE_DIR, 0o700)


def _cache_write(name, obj):
    try:
        ensure_cache_dir()
        tmp = os.path.join(CACHE_DIR, name + ".tmp")
        with open(tmp, "w") as fh:
            json.dump(obj, fh)
        os.replace(tmp, os.path.join(CACHE_DIR, name))
    except OSError:
        pass


def _cache_read(name):
    try:
        with open(os.path.join(CACHE_DIR, name)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _why(exc):
    """A short reason a fetch failed, fit for a narrow panel row.

    urllib wraps everything as '<urlopen error [Errno -3] Temporary failure in
    name resolution>', which says little and does not fit anywhere.
    """
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, socket.gaierror):
            return "no network"
        if isinstance(reason, TimeoutError):
            return "timed out"
        if reason is not None:
            return str(reason)
    if isinstance(exc, TimeoutError):
        return "timed out"
    return str(exc)


def _cache_read_versioned(name):
    """Cached reading, or None if it was written by a different build."""
    data = _cache_read(name)
    if isinstance(data, dict) and data.get("v") == QUOTA_CACHE_VERSION:
        return data
    return None


def _backoff_until(name):
    return (_cache_read(name) or {}).get("until", 0)


def _backoff_bump(name):
    """Double the wait after each rejection, within bounds."""
    prev = max(0.0, _backoff_until(name) - time.time())
    wait = min(_BACKOFF_MAX, max(_BACKOFF_MIN, prev * 2))
    _cache_write(name, {"until": time.time() + wait})
    return wait


def _backoff_clear(name):
    if _backoff_until(name):
        _cache_write(name, {"until": 0})


def _fresh_token(path, key, exp_key, exp_unit):
    """Return the access token if it is still valid, else (None, reason)."""
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None, "not signed in"
    node = data.get("claudeAiOauth", data)
    tok = node.get(key)
    exp = node.get(exp_key)
    if not tok:
        return None, "no token"
    if exp:
        exp_s = exp / 1000.0 if exp_unit == "ms" else float(exp)
        if exp_s <= time.time() + 30:
            return None, "token expired"
    return tok, None


def _find_cli(name, fallback):
    # A systemd user unit gets a bare PATH, so ~/.local/bin is often missing.
    return shutil.which(name) or (fallback if os.access(fallback, os.X_OK) else None)


def renew_claude_token():
    """Have Claude Code renew its own token, so we never refresh as Claude Code.

    `auth status` costs nothing; if it leaves the token expired, one minimal
    prompt does it, without tools, MCP servers or a saved session.
    """
    cli = _find_cli("claude", os.path.join(HOME, ".local", "bin", "claude"))
    if cli is None:
        return "claude not found"
    ensure_cache_dir()
    attempts = (
        ([cli, "auth", "status"], 20),
        ([cli, "-p", "ok", "--model", "haiku", "--tools", "", "--strict-mcp-config",
          "--no-session-persistence"], 120),
    )
    for argv, limit in attempts:
        try:
            subprocess.run(argv, cwd=CACHE_DIR, stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=limit, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if _fresh_token(CLAUDE_CREDS, "accessToken", "expiresAt", "ms")[0]:
            return None
    return "renew failed"


_KIMI_OAUTH_HOST = (os.environ.get("KIMI_CODE_OAUTH_HOST") or os.environ.get("KIMI_OAUTH_HOST")
                    or "https://auth.kimi.com").rstrip("/")
_KIMI_CLIENT_ID = "17e5f671-d194-4dfb-9706-5516cb48c098"


def _kimi_running():
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as fh:
                argv0 = fh.read().split(b"\0", 1)[0]
        except OSError:
            continue
        if os.path.basename(argv0) == b"kimi":
            return True
    return False


def _write_private_json(path, obj):
    tmp = path + ".agent-usage.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(obj, fh)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def renew_kimi_token(timeout=4):
    """Refresh Kimi's token the way kimi itself does, under kimi's own lock.

    The refresh token rotates, so a refresh racing kimi's would leave one side
    holding a dead token and the user signed out. Hence: never while a kimi
    process is running, never without the lock, and a lock that is held is
    waited for by nobody: kimi stamps its lock every few seconds, and if it is
    there, kimi is refreshing and will write the result itself.
    """
    if not _KIMI_OAUTH_HOST.startswith("https://"):
        return "oauth host is not https"
    if _kimi_running():
        return "kimi is running"
    try:
        os.makedirs(os.path.dirname(KIMI_REFRESH_LOCK), exist_ok=True)
        os.mkdir(KIMI_REFRESH_LOCK)
    except FileExistsError:
        return "kimi is refreshing"
    except OSError as exc:
        return _why(exc)
    # proper-lockfile treats a lock untouched for 5 s as stale and takes it
    # over, so the request timeout keeps the whole hold well under that.
    try:
        try:
            with open(KIMI_CREDS) as fh:
                creds = json.load(fh)
        except (OSError, ValueError):
            return "not signed in"
        if _fresh_token(KIMI_CREDS, "access_token", "expires_at", "s")[0]:
            return None
        refresh = creds.get("refresh_token")
        if not refresh:
            return "no refresh token"
        body = urllib.parse.urlencode({
            "client_id": _KIMI_CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": refresh,
        }).encode()
        req = urllib.request.Request(
            _KIMI_OAUTH_HOST + "/api/oauth/token", data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "application/json",
                     "User-Agent": "agent-usage-indicator/1.0"})
        try:
            with _OPENER.open(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return "refresh HTTP %d" % exc.code
        except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
            return _why(exc)
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
        try:
            _write_private_json(KIMI_CREDS, creds)
        except OSError as exc:
            return _why(exc)
        return None
    finally:
        try:
            os.rmdir(KIMI_REFRESH_LOCK)
        except OSError:
            pass


def claude_quota(timeout=8, fresh_for=QUOTA_FRESH_S, renew=False):
    """Real plan utilisation, from the same endpoint /usage calls in Claude Code."""
    cached = _cache_read_versioned("claude-quota.json")
    if cached and time.time() - cached.get("fetched_at", 0) < fresh_for:
        return dict(cached, from_cache=True)

    tok, why = _fresh_token(CLAUDE_CREDS, "accessToken", "expiresAt", "ms")
    if tok is None and renew and why == "token expired":
        failed = renew_claude_token()
        tok, why = _fresh_token(CLAUDE_CREDS, "accessToken", "expiresAt", "ms")
        why = failed or why
    if tok is None:
        return {"ok": False, "why": why, "cached": cached}
    wait = _backoff_until("claude-backoff.json") - time.time()
    if wait > 0:
        return {"ok": False, "why": "rate limited, retrying in %ds" % wait, "cached": cached}
    try:
        data = _get_json(
            "https://api.anthropic.com/api/oauth/usage",
            tok,
            timeout,
            {"anthropic-beta": "oauth-2025-04-20", "Content-Type": "application/json"},
        )
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            wait = _backoff_bump("claude-backoff.json")
            return {
                "ok": False,
                "why": "rate limited, retrying in %ds" % wait,
                "cached": cached,
            }
        return {"ok": False, "why": "HTTP %d" % exc.code, "cached": cached}
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
        return {"ok": False, "why": _why(exc), "cached": cached}
    _backoff_clear("claude-backoff.json")

    limits = []
    for lim in data.get("limits") or []:
        kind = lim.get("kind")
        if kind in _CLAUDE_SKIP_KINDS:
            continue
        label = _CLAUDE_LABELS.get(kind, kind or "?")
        limits.append(
            {
                "label": label,
                "percent": lim.get("percent"),
                "severity": lim.get("severity") or "normal",
                "resets_at": lim.get("resets_at"),
                "is_active": bool(lim.get("is_active")),
            }
        )
    extra = data.get("extra_usage") or {}
    out = {
        "ok": True,
        "v": QUOTA_CACHE_VERSION,
        "fetched_at": time.time(),
        "limits": limits,
        "extra_usage_enabled": bool(extra.get("is_enabled")),
        "extra_usage_percent": extra.get("utilization"),
    }
    _cache_write("claude-quota.json", out)
    return out


_KIMI_BASE = "https://api.kimi.com"
_KIMI_RAW_KEEP = frozenset({"usage", "usages", "limits"})

# Kimi Code documents no usage endpoint, so the working one has to be found by
# asking. The path that answers 200 is remembered and used alone afterwards; a
# sweep that finds nothing is remembered too, so seven requests do not go out
# every five minutes forever.
_KIMI_PATHS = (
    "/coding/v1/usages",
    "/coding/v1/usage",
    "/coding/v1/me",
    "/coding/v1/quota",
    "/coding/v1/quotas",
    "/coding/v1/subscription",
    "/coding/v1/limits",
)
_KIMI_RESWEEP_S = 86400

_PCT_KEYS = ("percent", "percentage", "utilization", "utilisation",
             "usage_percent", "used_percent", "usedPercent")
_USED_KEYS = ("used", "usage", "consumed", "current", "spent")
_CAP_KEYS = ("limit", "total", "quota", "max", "cap", "allowance")
_RESET_KEYS = ("resets_at", "resetAt", "reset_at", "reset_time", "resetTime",
               "refresh_at", "next_reset", "nextReset", "period_end", "periodEnd")
_NAME_KEYS = ("label", "name", "kind", "type", "window", "period", "scope", "id")


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


_TIME_UNIT_MIN = {"minute": 1, "hour": 60, "day": 1440, "week": 10080}


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
        # Kimi ends its stamps with Z, which fromisoformat only accepts from
        # Python 3.11; normalising here keeps fmt_reset working on any of them.
        return v[:-1] + "+00:00" if v.endswith("Z") else v
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


def _kimi_limits(data):
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
            rows = _kimi_limits(inner)
            if rows:
                return rows
    one = _as_limit(data)
    return [one] if one else []


def _kimi_probe(tok, timeout):
    """Sweep the candidate paths for one that reports usage, as (path, payload, rows).

    A path that answers 200 but carries no percentages does not win the sweep,
    it only becomes the fallback: /me answers for every signed-in user, so
    stopping at the first 200 would cache it as the endpoint and the real one
    would never be tried. A 401/403/429 is about the caller rather than the
    path, so it stops the sweep and is reported; only a 404 means keep looking.
    """
    known = _cache_read("kimi-endpoint.json") or {}
    if known.get("path"):
        paths = [known["path"]] + [p for p in _KIMI_PATHS if p != known["path"]]
    elif time.time() - known.get("swept_at", 0) < _KIMI_RESWEEP_S:
        return None, None, []  # a full sweep came up empty recently
    else:
        paths = list(_KIMI_PATHS)

    fallback = (None, None)
    for path in paths:
        try:
            data = _get_json(_KIMI_BASE + path, tok, timeout)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 429):
                raise
            continue
        rows = _kimi_limits(data)
        if rows:
            _cache_write("kimi-endpoint.json", {"path": path, "found_at": time.time()})
            return path, data, rows
        if fallback[0] is None:
            fallback = (path, data)
    _cache_write("kimi-endpoint.json", {"path": None, "swept_at": time.time()})
    return fallback[0], fallback[1], []


def kimi_quota(timeout=8, fresh_for=QUOTA_FRESH_S, renew=False):
    """Real usage from Kimi's own API, if it will give any.

    Kimi Code's access token lives 15 minutes, so outside an active kimi session
    it is usually expired. Only an explicit Refresh renews it (renew=True); the
    timed loop never spends the rotating refresh token on its own."""
    cached = _cache_read_versioned("kimi-quota.json")
    if cached and time.time() - cached.get("fetched_at", 0) < fresh_for:
        return dict(cached, from_cache=True)

    tok, why = _fresh_token(KIMI_CREDS, "access_token", "expires_at", "s")
    if tok is None and renew and why == "token expired":
        failed = renew_kimi_token()
        tok, why = _fresh_token(KIMI_CREDS, "access_token", "expires_at", "s")
        why = failed or why
    if tok is None:
        return {"ok": False, "why": why, "cached": cached}
    wait = _backoff_until("kimi-backoff.json") - time.time()
    if wait > 0:
        return {"ok": False, "why": "rate limited, retrying in %ds" % wait, "cached": cached}
    try:
        path, data, limits = _kimi_probe(tok, timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            wait = _backoff_bump("kimi-backoff.json")
            return {"ok": False, "why": "rate limited, retrying in %ds" % wait, "cached": cached}
        return {"ok": False, "why": "HTTP %d" % exc.code, "cached": cached}
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
        return {"ok": False, "why": _why(exc), "cached": cached}
    _backoff_clear("kimi-backoff.json")

    if path is None:
        return {"ok": False, "why": "no usage endpoint", "cached": cached}

    # Keep the usage part of the real reply, the only record of what the API
    # actually sends. The rest (account and subscription ids, the top-up wallet)
    # is not ours to keep, so only its key names are recorded.
    kept = {k: v for k, v in data.items() if k in _KIMI_RAW_KEEP} if isinstance(data, dict) else data
    other = sorted(set(data) - _KIMI_RAW_KEEP) if isinstance(data, dict) else []
    _cache_write("kimi-raw.json", {"path": path, "at": time.time(), "data": kept,
                                   "dropped_keys": other})

    if not limits:
        return {"ok": False, "why": "no percentages at %s" % path.rsplit("/", 1)[-1],
                "cached": cached}
    out = {
        "ok": True,
        "v": QUOTA_CACHE_VERSION,
        "fetched_at": time.time(),
        "path": path,
        "limits": limits,
    }
    _cache_write("kimi-quota.json", out)
    return out


def _reset_passed(iso, now=None):
    """True once a reset stamp has gone by.

    A stamp with no timezone is read as local, the same way fmt_reset reads it.
    """
    if not iso:
        return False
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.timestamp() <= (time.time() if now is None else now)


def live_limits(quota):
    """(limits, live, why) for one tool's reading.

    A cached reading outlives the window it measured. Once its reset time has
    gone by the window has rolled over, so the old percentage describes a
    period that no longer exists and is dropped. Dropped rather than zeroed:
    what the new window holds is unknown until a fetch succeeds, and this tool
    does not show a number it has not been told.
    """
    if quota.get("ok"):
        return quota.get("limits") or [], True, None
    cached = (quota.get("cached") or {}).get("limits") or []
    kept = [lim for lim in cached if not _reset_passed(lim.get("resets_at"))]
    return kept, False, quota.get("why")


# --------------------------------------------------------------------------


class Collector:
    """Keeps the scanners alive between refreshes so only new bytes are read."""

    def __init__(self):
        self.claude = Scanner(CLAUDE_GLOB, _claude_extract)
        self.kimi = Scanner(KIMI_GLOB, _kimi_extract)
        self._quota = {"claude": None, "kimi": None}
        self._quota_at = 0.0

    def local(self):
        return {
            "claude": summarize(self.claude.scan()),
            "kimi": summarize(self.kimi.scan()),
        }

    def quota(self, max_age=180, force=False):
        if force or time.time() - self._quota_at > max_age or self._quota["claude"] is None:
            self._quota = {"claude": claude_quota(), "kimi": kimi_quota()}
            self._quota_at = time.time()
        return self._quota

    def snapshot(self, force_quota=False):
        return {"local": self.local(), "quota": self.quota(force=force_quota), "at": time.time()}


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------


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
        name = name[len("claude-") :]
    return name


def fmt_reset(iso):
    """ISO UTC -> local 'HH:MM' today, 'Fri 09:00' within the week, else 'Aug 18, 16:00'."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso).astimezone()
    except ValueError:
        return ""
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
