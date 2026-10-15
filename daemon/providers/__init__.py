"""Every coding agent this tool knows, in the order they are shown.

Adding one is a module in this package that builds a base.Provider, plus its
line here. The extension needs no change: it draws whatever state.json lists.
"""
from __future__ import annotations

from providers import claude, kimi

PROVIDERS = (claude.PROVIDER, kimi.PROVIDER)
BY_TAG = {p.tag: p for p in PROVIDERS}
