"""Small JSON files in the cache directory: quota readings and backoff stamps.

The daemon and the terminal command share these, so a reading one of them
fetched spares the other a request against a rate-limited endpoint.
"""
from __future__ import annotations

import json
import os
import time

import paths

# Bump when a cached reading's shape or labels change, so readings written by an
# older build are discarded instead of surfacing with stale wording.
VERSION = 5

# A cached reading younger than this is served without touching the network.
FRESH_S = 120

_BACKOFF_MIN, _BACKOFF_MAX = 60.0, 900.0
# A rejection this long after the previous one is treated as unrelated, so the
# wait starts from the minimum again instead of from where yesterday left off.
_BACKOFF_FORGET = 3600.0


def write(name, obj):
    try:
        paths.ensure_cache_dir()
        tmp = os.path.join(paths.CACHE_DIR, name + ".tmp")
        with open(tmp, "w") as fh:
            json.dump(obj, fh)
        os.replace(tmp, os.path.join(paths.CACHE_DIR, name))
    except OSError:
        pass


def read(name):
    try:
        with open(os.path.join(paths.CACHE_DIR, name)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def read_versioned(name):
    """Cached reading, or None when it cannot be trusted.

    The version check alone is not enough: it says which build wrote the file,
    not that the file still holds what that build wrote. Everything read back
    is fed to arithmetic and to date parsing, so the shape is checked here,
    once, rather than guarded again at each use.
    """
    data = read(name)
    if not isinstance(data, dict) or data.get("v") != VERSION:
        return None
    if not isinstance(data.get("fetched_at"), (int, float)) or isinstance(
        data.get("fetched_at"), bool
    ):
        return None
    limits = data.get("limits")
    if limits is not None and (
        not isinstance(limits, list) or not all(isinstance(x, dict) for x in limits)
    ):
        return None
    return data


def backoff_until(name):
    return (read(name) or {}).get("until", 0)


def backoff_bump(name):
    """Double the wait after each rejection, within bounds.

    The wait is remembered next to the deadline rather than derived from the
    time left on it. Deriving it could not work: the caller returns early for
    as long as the deadline stands, so this is only ever reached once the
    deadline has passed, when the time left is zero and every doubling
    collapsed back to the minimum.

    A rejection long after the last one starts over, so an endpoint that was
    unhappy yesterday does not begin today at a quarter of an hour.
    """
    state = read(name) or {}
    prev = state.get("wait")
    if not isinstance(prev, (int, float)) or isinstance(prev, bool) or prev <= 0:
        prev = 0.0
    last = state.get("until", 0)
    if not isinstance(last, (int, float)) or time.time() - last > _BACKOFF_FORGET:
        prev = 0.0
    wait = min(_BACKOFF_MAX, max(_BACKOFF_MIN, prev * 2))
    write(name, {"until": time.time() + wait, "wait": wait})
    return wait


def backoff_clear(name):
    if backoff_until(name):
        write(name, {"until": 0, "wait": 0})
