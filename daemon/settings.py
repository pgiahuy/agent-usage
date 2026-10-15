"""The user's choices, read from the extension's GSettings schema.

The collector is standard library only, so it reads them with the gsettings
command; the schema is compiled inside the extension, hence --schemadir. When
nothing can be read, every key falls back to its built-in default.
"""
from __future__ import annotations

import ast
import os
import subprocess

import paths
from providers import PROVIDERS

SCHEMA = "org.gnome.shell.extensions.agent-usage"
UUID = "agent-usage@pgiahuy.github.io"
_SCHEMA_DIRS = (
    os.path.join(os.environ.get("XDG_DATA_HOME", os.path.join(paths.HOME, ".local", "share")),
                 "gnome-shell", "extensions", UUID, "schemas"),
    os.path.join("/usr/share/gnome-shell/extensions", UUID, "schemas"),
)


def get(key):
    """One key, as gsettings prints it, or None."""
    for schema_dir in _SCHEMA_DIRS:
        if not os.path.exists(os.path.join(schema_dir, "gschemas.compiled")):
            continue
        try:
            out = subprocess.run(
                ["gsettings", "--schemadir", schema_dir, "get", SCHEMA, key],
                capture_output=True, text=True, timeout=5, check=True,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
        return out or None
    return None


def quota_every(default):
    """Seconds between quota checks. A uint32 prints as "uint32 5"."""
    raw = get("quota-interval")
    try:
        return int(raw.split()[-1]) * 60
    except (AttributeError, ValueError, IndexError):
        return default


def hidden_tools():
    """Tags the user switched off. An array of strings prints as "['kimi']",
    or "@as []" when empty."""
    raw = get("hidden-tools")
    if not raw:
        return set()
    if raw.startswith("@as "):
        raw = raw[4:]
    try:
        value = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return set()
    return {v for v in value if isinstance(v, str)} if isinstance(value, list) else set()


def visible(providers=PROVIDERS):
    """Providers to collect and show: not hidden, and installed at all."""
    hidden = hidden_tools()
    return [p for p in providers if p.tag not in hidden and p.installed]
