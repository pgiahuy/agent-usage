"""Imported first by every test module: point every path the collector reads
or writes at a throwaway directory, before any collector module is imported
(they resolve their paths at import time), and put daemon/ on sys.path."""
import atexit
import os
import shutil
import sys
import tempfile

ROOT = tempfile.mkdtemp(prefix="agent-usage-test-")
atexit.register(shutil.rmtree, ROOT, True)

os.environ["XDG_CACHE_HOME"] = os.path.join(ROOT, "cache")
os.environ["XDG_DATA_HOME"] = os.path.join(ROOT, "data")
os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(ROOT, "claude")
os.environ["KIMI_CODE_HOME"] = os.path.join(ROOT, "kimi")
for var in ("KIMI_CODE_OAUTH_HOST", "KIMI_OAUTH_HOST"):
    os.environ.pop(var, None)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "daemon"))
