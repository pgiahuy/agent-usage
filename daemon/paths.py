"""Where things live: each tool's data directory, and this tool's cache."""
from __future__ import annotations

import os

HOME = os.path.expanduser("~")


def tool_home(env_var, default_name):
    """Where a tool keeps its data. Neither location is ours to assume: Claude
    Code moves with CLAUDE_CONFIG_DIR and Kimi Code with KIMI_CODE_HOME, and a
    user who has set either would otherwise just see an empty panel."""
    override = os.environ.get(env_var)
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return os.path.join(HOME, default_name)


CACHE_DIR = os.path.join(
    os.environ.get("XDG_CACHE_HOME", os.path.join(HOME, ".cache")), "agent-usage"
)


def ensure_cache_dir():
    """Create the cache directory private to the user, and make it so if an
    older build left it group-writable: it holds quota readings and Kimi's raw
    usage reply."""
    os.makedirs(CACHE_DIR, mode=0o700, exist_ok=True)
    if os.stat(CACHE_DIR).st_mode & 0o077:
        os.chmod(CACHE_DIR, 0o700)
