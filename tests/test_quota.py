import _env  # noqa: F401  (must come first)

import json
import os
import time
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone

import cache
import paths
import quota
from providers import kimi
from providers.base import Provider


class FakeProvider:
    """Records calls; token validity and the fetch outcome are set per test."""

    def __init__(self, tag):
        self.calls = []
        self.valid = True
        self.outcome = {"limits": [{"label": "5-hour", "percent": 12}]}
        self.provider = Provider(
            tag=tag, name=tag.upper(), accent="#000000", home=_env.ROOT, log_glob="",
            extract=lambda raw: None, token=self.token, fetch=self.fetch, renew=self.renew)

    def token(self):
        return ("TOK", None) if self.valid else (None, "token expired")

    def fetch(self, tok, timeout):
        self.calls.append("fetch")
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    def renew(self):
        self.calls.append("renew")
        self.valid = True
        return None


class FetchTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeProvider("fake%d" % id(self))

    def test_success_is_cached_and_served(self):
        first = quota.fetch(self.fake.provider)
        self.assertTrue(first["ok"])
        second = quota.fetch(self.fake.provider)
        self.assertTrue(second.get("from_cache"))
        self.assertEqual(self.fake.calls, ["fetch"])

    def test_expired_token_is_renewed_only_when_asked(self):
        self.fake.valid = False
        self.assertEqual(quota.fetch(self.fake.provider, fresh_for=0)["why"], "token expired")
        self.assertEqual(self.fake.calls, [])
        self.assertTrue(quota.fetch(self.fake.provider, fresh_for=0, renew=True)["ok"])
        self.assertEqual(self.fake.calls, ["renew", "fetch"])

    def test_429_backs_off(self):
        self.fake.outcome = urllib.error.HTTPError("u", 429, "Too Many", {}, None)
        self.assertIn("rate limited", quota.fetch(self.fake.provider, fresh_for=0)["why"])
        self.fake.outcome = {"limits": []}
        self.assertIn("rate limited", quota.fetch(self.fake.provider, fresh_for=0)["why"])
        self.assertEqual(self.fake.calls, ["fetch"])  # the second call never went out

    def test_each_rejection_doubles_the_wait(self):
        """The wait used to collapse back to the minimum every time.

        It was derived from the time left on the previous deadline, but fetch
        returns early for as long as that deadline stands, so the bump only
        ran once it had passed, when the time left was zero. The result was a
        constant 60s against an endpoint that rate-limits hard, and the
        900s ceiling was unreachable.
        """
        self.fake.outcome = urllib.error.HTTPError("u", 429, "Too Many", {}, None)
        name = "%s-backoff.json" % self.fake.provider.tag
        waits = []
        for _ in range(5):
            quota.fetch(self.fake.provider, fresh_for=0)
            state = cache.read(name)
            waits.append(round(state["wait"]))
            # Let the window lapse, which is the only state fetch will ask again in.
            cache.write(name, dict(state, until=time.time() - 1))
        self.assertEqual(waits, [60, 120, 240, 480, 900])

        # A success wipes it, so the next rejection starts from the minimum.
        self.fake.outcome = {"limits": []}
        quota.fetch(self.fake.provider, fresh_for=0)
        self.fake.outcome = urllib.error.HTTPError("u", 429, "Too Many", {}, None)
        quota.fetch(self.fake.provider, fresh_for=0)
        self.assertEqual(round(cache.read(name)["wait"]), 60)

    def test_unavailable_reports_its_reason(self):
        self.fake.outcome = quota.Unavailable("no usage endpoint")
        reading = quota.fetch(self.fake.provider, fresh_for=0)
        self.assertEqual((reading["ok"], reading["why"]), (False, "no usage endpoint"))


class LiveLimitsTest(unittest.TestCase):
    def test_cached_limits_past_their_reset_are_dropped(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        reading = {"ok": False, "why": "no network", "cached": {"limits": [
            {"label": "5-hour", "resets_at": past}, {"label": "Weekly", "resets_at": future}]}}
        limits, live, why = quota.live_limits(reading)
        self.assertEqual([lim["label"] for lim in limits], ["Weekly"])
        self.assertEqual((live, why), (False, "no network"))


class ReadTokenTest(unittest.TestCase):
    def write(self, obj):
        path = os.path.join(_env.ROOT, "creds-%d.json" % id(obj))
        with open(path, "w") as fh:
            json.dump(obj, fh)
        return path

    def test_nested_token_with_ms_expiry(self):
        later_ms = (time.time() + 3600) * 1000
        path = self.write({"claudeAiOauth": {"accessToken": "A", "expiresAt": later_ms}})
        token = quota.read_token(path, "accessToken", "expiresAt", "ms", node="claudeAiOauth")
        self.assertEqual(token, ("A", None))

    def test_expired_and_missing(self):
        path = self.write({"access_token": "A", "expires_at": time.time() - 1})
        self.assertEqual(quota.read_token(path, "access_token", "expires_at", "s"),
                         (None, "token expired"))
        self.assertEqual(quota.read_token("/nonexistent", "a", "b", "s"), (None, "not signed in"))


class KimiReplyTest(unittest.TestCase):
    # The real shape of /coding/v1/usages: every number is a string, and the
    # rolling window says what is left, not what was spent.
    REPLY = {
        "usage": {"limit": "100", "used": "83", "remaining": "17",
                  "resetTime": "2026-10-17T13:45:00Z"},
        "limits": [{"window": {"duration": 300, "timeUnit": "TIME_UNIT_MINUTE"},
                    "detail": {"limit": "100", "remaining": "96",
                               "resetTime": "2026-10-15T07:45:00Z"}}],
        "booster_wallet": {"userId": "U-PRIVATE", "subscriptionId": "S-PRIVATE"},
    }

    def test_parse(self):
        rows = kimi.parse_limits(self.REPLY)
        self.assertEqual([(r["label"], r["percent"]) for r in rows], [("5-hour", 4), ("Plan", 83)])
        self.assertTrue(rows[0]["resets_at"].endswith("+00:00"))

    def test_raw_reply_keeps_usage_only(self):
        saved = kimi._probe
        kimi._probe = lambda tok, timeout: ("/coding/v1/usages", self.REPLY,
                                            kimi.parse_limits(self.REPLY))
        try:
            kimi.fetch("TOK", 5)
        finally:
            kimi._probe = saved
        raw = cache.read("kimi-raw.json")
        self.assertEqual(sorted(raw["data"]), ["limits", "usage"])
        self.assertEqual(raw["dropped_keys"], ["booster_wallet"])
        self.assertNotIn("PRIVATE", json.dumps(raw))

    def test_cache_dir_is_private(self):
        paths.ensure_cache_dir()
        os.chmod(paths.CACHE_DIR, 0o775)  # as an older build left it
        cache.write("x.json", {})
        self.assertEqual(os.stat(paths.CACHE_DIR).st_mode & 0o777, 0o700)


if __name__ == "__main__":
    unittest.main()
