"""What the rest of the collector needs to know about one coding agent."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Optional, Tuple


@dataclass(frozen=True)
class Provider:
    # Id used by the settings (hidden-tools), state.json and the cache file names.
    tag: str
    # Header in the popup and the terminal view.
    name: str
    # Brand colour for the header, the badge and the "no reading" dot.
    accent: str
    # The agent's data directory. Absent means the agent never ran here, and
    # the provider is left out instead of showing "not signed in" forever.
    home: str
    # Session logs to count tokens from, and how to read one line of them:
    # bytes -> (epoch, model, dedup_key, inp, out, cache_read, cache_write) or None.
    log_glob: str
    extract: Callable[[bytes], Optional[tuple]]
    # () -> (access token, None) or (None, reason).
    token: Callable[[], Tuple[Optional[str], Optional[str]]]
    # (token, timeout) -> {"limits": [...], ...}. May raise urllib errors or
    # quota.Unavailable; quota.fetch() turns those into a reason.
    fetch: Callable[[str, float], dict]
    # (rejected=None) -> None once the token is valid again, else the reason it
    # is not. rejected is a token the server refused before it expired: the
    # stored copy still looks valid then, so only a different one will do.
    renew: Callable[..., Optional[str]]

    @property
    def installed(self):
        return os.path.isdir(self.home)
