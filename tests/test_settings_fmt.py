import _env  # noqa: F401  (must come first)

import dataclasses
import os
import unittest

import fmt
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
