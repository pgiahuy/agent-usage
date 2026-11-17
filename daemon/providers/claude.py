"""Claude Code.

Tokens: ~/.claude/projects/**/*.jsonl, one line per message; assistant lines
carry message.usage.
Quota: GET https://api.anthropic.com/api/oauth/usage, the endpoint Claude
Code's own /usage calls, with the OAuth token from ~/.claude/.credentials.json.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from datetime import datetime

import net
import paths
import quota
from providers.base import Provider

HOME = paths.tool_home("CLAUDE_CONFIG_DIR", ".claude")
LOG_GLOB = os.path.join(HOME, "projects", "**", "*.jsonl")
CREDS = os.path.join(HOME, ".credentials.json")
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"

_LABELS = {"session": "5-hour", "weekly_all": "Weekly"}

# The per-model weekly cap ("weekly_scoped"). Dropped on request: it is a third
# bar that mostly tracks the plain weekly one, and its model name never fit the
# panel's name column.
_SKIP_KINDS = {"weekly_scoped"}


def extract(raw):
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
    inp = int(u.get("input_tokens") or 0)
    out = int(u.get("output_tokens") or 0)
    cread = int(u.get("cache_read_input_tokens") or 0)
    cwrite = int(u.get("cache_creation_input_tokens") or 0)
    # A resumed or forked session replays earlier messages into the new file;
    # message id + request id identify a reply however often it is copied. A
    # record with neither is keyed on its own contents instead, which a replay
    # copies byte for byte. That key is a tuple, so it can never equal an id
    # key, which is always a string.
    mid, rid = msg.get("id"), d.get("requestId")
    if mid or rid:
        key = "%s|%s" % (mid or "", rid or "")
    else:
        key = (ts, model, inp, out, cread, cwrite)
    return (epoch, model, key, inp, out, cread, cwrite)


def token():
    return quota.read_token(CREDS, "accessToken", "expiresAt", "ms", node="claudeAiOauth")


def fetch(tok, timeout):
    data = net.get_json(
        USAGE_URL, tok, timeout,
        {"anthropic-beta": "oauth-2025-04-20", "Content-Type": "application/json"},
    )
    limits = []
    for lim in data.get("limits") or []:
        kind = lim.get("kind")
        if kind in _SKIP_KINDS:
            continue
        limits.append({
            "label": _LABELS.get(kind, kind or "?"),
            "percent": lim.get("percent"),
            "severity": lim.get("severity") or "normal",
            "resets_at": lim.get("resets_at"),
            "is_active": bool(lim.get("is_active")),
        })
    extra = data.get("extra_usage") or {}
    return {
        "limits": limits,
        "extra_usage_enabled": bool(extra.get("is_enabled")),
        "extra_usage_percent": extra.get("utilization"),
    }


def _find_cli():
    # A systemd user unit gets a bare PATH, so ~/.local/bin is often missing.
    fallback = os.path.join(paths.HOME, ".local", "bin", "claude")
    return shutil.which("claude") or (fallback if os.access(fallback, os.X_OK) else None)


# The whole renew shares one budget. It runs on the daemon's only thread, so
# for as long as it lasts the per-second SIGTERM check does not run, and
# systemctl stop waits out its timeout and then SIGKILLs. Two attempts at
# their own generous timeouts used to add up to well over two minutes.
_RENEW_BUDGET_S = 45.0


def _run_briefly(argv, limit):
    """Run argv, giving up after limit seconds. True when it exited by itself.

    Its own session, so a timeout can signal the whole group: claude spawns
    node children, and killing the direct child alone would leave them
    running.
    """
    try:
        proc = subprocess.Popen(
            argv, cwd=paths.CACHE_DIR, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return False
    try:
        proc.wait(timeout=limit)
        return True
    except subprocess.TimeoutExpired:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, sig)
            except OSError:
                break
            try:
                proc.wait(timeout=2)
                break
            except subprocess.TimeoutExpired:
                continue
        return False


def renew(rejected=None):
    """Have Claude Code renew its own token, so nothing here acts as Claude Code.

    `auth status` costs nothing; if it leaves the token expired, one minimal
    prompt does it, without tools, MCP servers or a saved session.

    rejected is a token the server refused before it expired. The copy on disk
    still looks valid then, so it counts as renewed only once it is a
    different token, which in practice means the prompt: it is the attempt
    that makes a request and meets the refusal.
    """
    cli = _find_cli()
    if cli is None:
        return "claude not found"
    paths.ensure_cache_dir()
    deadline = time.monotonic() + _RENEW_BUDGET_S
    attempts = (
        [cli, "auth", "status"],
        [cli, "-p", "ok", "--model", "haiku", "--tools", "", "--strict-mcp-config",
         "--no-session-persistence"],
    )
    for argv in attempts:
        left = deadline - time.monotonic()
        if left <= 1:
            return "renew timed out"
        if not _run_briefly(argv, left):
            continue
        tok = token()[0]
        if tok and tok != rejected:
            return None
    return "renew failed"


PROVIDER = Provider(
    tag="claude",
    name="CLAUDE",
    accent="#e08a6c",
    home=HOME,
    log_glob=LOG_GLOB,
    extract=extract,
    token=token,
    fetch=fetch,
    renew=renew,
)
