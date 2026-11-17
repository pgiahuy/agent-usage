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
        self.tok = "TOK"
        self.sent = []      # the token each request went out with
        self.rejected = []  # what each renew was told had been refused
        # The token a renewal stores. None leaves the stored one as it was,
        # which is what a renewal that only checks expiry does to a refused one.
        self.renews_to = None
        # One outcome for every request, or a list taken in order.
        self.outcome = {"limits": [{"label": "5-hour", "percent": 12}]}
        self.provider = Provider(
            tag=tag, name=tag.upper(), accent="#000000", home=_env.ROOT, log_glob="",
            extract=lambda raw: None, token=self.token, fetch=self.fetch, renew=self.renew)

    def token(self):
        return (self.tok, None) if self.valid else (None, "token expired")

    def fetch(self, tok, timeout):
        self.calls.append("fetch")
        self.sent.append(tok)
        outcome = self.outcome.pop(0) if isinstance(self.outcome, list) else self.outcome
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def renew(self, rejected=None):
        self.calls.append("renew")
        self.rejected.append(rejected)
        self.valid = True
        if self.renews_to is not None:
            self.tok = self.renews_to
        return None


def http(code):
    return urllib.error.HTTPError("u", code, "x", {}, None)


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

    def test_a_refused_token_is_renewed_once_and_retried(self):
        self.fake.outcome = [http(401), {"limits": []}]
        self.fake.renews_to = "NEW"
        self.assertTrue(quota.fetch(self.fake.provider, fresh_for=0, renew=True)["ok"])
        self.assertEqual(self.fake.calls, ["fetch", "renew", "fetch"])
        self.assertEqual(self.fake.rejected, ["TOK"])
        self.assertEqual(self.fake.sent, ["TOK", "NEW"])

    def test_a_renewal_that_leaves_the_token_as_it_was_is_not_retried(self):
        # The refused token is still the stored one, and still looks valid, so
        # a renewal that only checks expiry calls itself done. Asking again
        # with it would only be refused again.
        self.fake.outcome = [http(401), {"limits": []}]
        reading = quota.fetch(self.fake.provider, fresh_for=0, renew=True)
        self.assertEqual((reading["ok"], reading["why"]), (False, "HTTP 401"))
        self.assertEqual(self.fake.calls, ["fetch", "renew"])

    def test_the_timed_loop_never_renews_a_refused_token(self):
        self.fake.outcome = http(401)
        self.fake.renews_to = "NEW"
        self.assertEqual(quota.fetch(self.fake.provider, fresh_for=0)["why"], "HTTP 401")
        self.assertEqual(self.fake.calls, ["fetch"])

    def test_a_retry_that_is_rate_limited_backs_off(self):
        self.fake.outcome = [http(401), http(429)]
        self.fake.renews_to = "NEW"
        reading = quota.fetch(self.fake.provider, fresh_for=0, renew=True)
        self.assertIn("rate limited", reading["why"])
        state = cache.read("%s-backoff.json" % self.fake.provider.tag)
        self.assertEqual(round(state["wait"]), 60)

    def test_a_retry_that_is_refused_again_is_reported_after_one_renewal(self):
        self.fake.outcome = [http(401), http(401)]
        self.fake.renews_to = "NEW"
        reading = quota.fetch(self.fake.provider, fresh_for=0, renew=True)
        self.assertEqual(reading["why"], "HTTP 401")
        self.assertEqual(self.fake.calls, ["fetch", "renew", "fetch"])

    def test_a_403_is_not_renewed(self):
        # Renewing cannot fix a refusal of permission, and costs a real
        # rotation or a prompt every time it is tried.
        self.fake.outcome = http(403)
        self.fake.renews_to = "NEW"
        reading = quota.fetch(self.fake.provider, fresh_for=0, renew=True)
        self.assertEqual(reading["why"], "HTTP 403")
        self.assertEqual(self.fake.calls, ["fetch"])

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
