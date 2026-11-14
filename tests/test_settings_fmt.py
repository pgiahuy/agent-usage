import _env  # noqa: F401  (must come first)

import dataclasses
import os
import unittest
from datetime import datetime

import fmt
import quota
import settings
from providers import PROVIDERS


class HiddenToolsTest(unittest.TestCase):
    def setUp(self):
        self.saved = settings.get

    def tearDown(self):
        settings.get = self.saved

    def parse(self, raw):
        settings.get = lambda key: raw
        return settings.hidden_tools()

    def test_gsettings_output(self):
        self.assertEqual(self.parse("@as []"), set())
        self.assertEqual(self.parse("['kimi']"), {"kimi"})
        self.assertEqual(self.parse("['claude', 'kimi']"), {"claude", "kimi"})

    def test_unreadable(self):
        for raw in (None, "garbage[", "'kimi'"):
            self.assertEqual(self.parse(raw), set())

    def test_visible_skips_hidden_and_not_installed(self):
        homes = {p.tag: os.path.join(_env.ROOT, "visible", p.tag) for p in PROVIDERS}
        providers = [dataclasses.replace(p, home=homes[p.tag]) for p in PROVIDERS]
        for home in homes.values():
            os.makedirs(home)
        self.parse("@as []")
        self.assertEqual([p.tag for p in settings.visible(providers)], ["claude", "kimi"])
        self.parse("['claude']")
        self.assertEqual([p.tag for p in settings.visible(providers)], ["kimi"])
        os.rmdir(homes["kimi"])
        self.assertEqual([p.tag for p in settings.visible(providers)], [])

    def test_no_schema_means_defaults(self):
        self.assertIsNone(self.saved("quota-interval"))
        self.assertEqual(settings.quota_every(300), 300)


class FmtTest(unittest.TestCase):
    def test_tokens(self):
        self.assertEqual([fmt.fmt_tokens(n) for n in (999, 60_000, 2_500_000, 3_100_000_000)],
                         ["999", "60k", "2.5M", "3.1B"])

    def test_bar_never_hides_usage(self):
        self.assertEqual(fmt.bar(0), ("", "█" * 10))
        self.assertEqual(len(fmt.bar(1)[0]), 1)  # any usage at all shows
        self.assertEqual(len(fmt.bar(99)[0]), 9)  # only a true 100% fills it
        self.assertEqual(fmt.bar(100), ("█" * 10, ""))

    def test_short_model(self):
        self.assertEqual(fmt.short_model("anthropic/claude-opus-5-5"), "opus-5-5")


class ResetStampTest(unittest.TestCase):
    """A reset stamp ending in Z has to parse on every Python we support.

    datetime.fromisoformat only learned to read a trailing Z in 3.11, and the
    collector supports 3.8. Kimi sends Z; Anthropic currently sends +00:00 but
    is not promised to keep doing so. If a stamp fails to parse, fmt_reset
    shows nothing and reset_passed answers False for ever, so a window that has
    rolled over keeps its old percentage on screen as though it were current.

    The stub below makes the older behaviour the test's own, so this fails on
    any version if the normalising is removed, not only on 3.8 to 3.10.
    """

    class _Strict:
        """datetime as it behaves before 3.11: a trailing Z is a ValueError."""

        @staticmethod
        def fromisoformat(text):
            if text.endswith("Z"):
                raise ValueError("Invalid isoformat string: %r" % text)
            return datetime.fromisoformat(text)

    def setUp(self):
        self.saved = fmt.datetime
        fmt.datetime = self._Strict

    def tearDown(self):
        fmt.datetime = self.saved

    def test_a_stamp_ending_in_z_is_read(self):
        dt = fmt.parse_iso("2026-11-21T13:45:53.362774Z")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.utcoffset().total_seconds(), 0)
        self.assertEqual(dt.year, 2026)

    def test_a_stamp_ending_in_z_counts_as_passed_once_it_is_over(self):
        self.assertTrue(quota.reset_passed("2020-01-01T00:00:00Z"))
        self.assertFalse(quota.reset_passed("2099-01-01T00:00:00Z"))

    def test_an_offset_stamp_still_works(self):
        self.assertTrue(quota.reset_passed("2020-01-01T00:00:00+00:00"))
        self.assertIsNotNone(fmt.parse_iso("2020-01-01T00:00:00+00:00"))

    def test_what_is_not_a_stamp_is_not_one(self):
        for junk in (None, "", "junk", 17, "Z"):
            self.assertIsNone(fmt.parse_iso(junk))
            self.assertFalse(quota.reset_passed(junk))


class QuotaIntervalTest(unittest.TestCase):
    def setUp(self):
        self.real = settings.get
        self.addCleanup(lambda: setattr(settings, "get", self.real))

    def answer(self, raw):
        settings.get = lambda key: raw

    def test_out_of_range_values_are_clamped(self):
        """The schema says 2 to 60 minutes, but dconf does not enforce a range
        on a value written straight into it, and a 0 asked for a quota call on
        every pass against an endpoint that rate-limits hard."""
        self.answer("uint32 0")
        self.assertEqual(settings.quota_every(300), settings.MIN_QUOTA_S)
        self.answer("uint32 100000")
        self.assertEqual(settings.quota_every(300), settings.MAX_QUOTA_S)
        self.answer("uint32 5")
        self.assertEqual(settings.quota_every(300), 300)

    def test_an_unreadable_value_keeps_the_default(self):
        self.answer(None)
        self.assertEqual(settings.quota_every(300), 300)
        self.answer("nonsense")
        self.assertEqual(settings.quota_every(300), 300)


if __name__ == "__main__":
    unittest.main()
