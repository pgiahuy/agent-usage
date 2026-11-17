import _env  # noqa: F401  (must come first)

import time
import unittest
from datetime import datetime, timedelta, timezone

import daemon
import scan
from providers import claude


def stamp(hours):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


class CheckedTest(unittest.TestCase):
    """How old the figures on screen are, for the popup to say so.

    state.json is rewritten every pass, so its own time says nothing about
    the quota figures in it, which are fetched every few minutes at most.
    """

    def state(self, reading):
        return daemon.tool_state(claude.PROVIDER, scan.summarize({}), reading)

    def test_live_figures_carry_the_time_they_were_fetched(self):
        fetched = time.time() - 240
        tool = self.state({"ok": True, "fetched_at": fetched,
                           "limits": [{"label": "5-hour", "percent": 12, "resets_at": stamp(2)}]})
        self.assertEqual(tool["checked"], fetched)
        self.assertFalse(tool["stale"])

    def test_figures_kept_from_the_cache_carry_the_cache_time(self):
        cached = time.time() - 3600
        tool = self.state({"ok": False, "why": "HTTP 500", "cached": {
            "fetched_at": cached,
            "limits": [{"label": "Weekly", "percent": 40, "resets_at": stamp(48)}]}})
        self.assertEqual(tool["checked"], cached)
        self.assertTrue(tool["stale"])

    def test_no_figures_means_no_time(self):
        self.assertIsNone(self.state({"ok": False, "why": "not signed in"})["checked"])
        # Everything cached has rolled over, so nothing is shown and nothing dated.
        old = self.state({"ok": False, "why": "HTTP 500", "cached": {
            "fetched_at": time.time() - 86400,
            "limits": [{"label": "5-hour", "percent": 90, "resets_at": stamp(-1)}]}})
        self.assertEqual(old["limits"], [])
        self.assertIsNone(old["checked"])


if __name__ == "__main__":
    unittest.main()
