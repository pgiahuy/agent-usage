import _env  # noqa: F401  (must come first)

import unittest

from providers import claude


class RenewTest(unittest.TestCase):
    """Claude Code renews its own token; renew() only judges whether it did.

    The CLI is never run here: each attempt is recorded, and the stored token
    is whatever the test says it is after that attempt.
    """

    def setUp(self):
        self.saved = (claude._find_cli, claude._run_briefly, claude.token)
        self.ran = []
        self.stored = {}  # attempt -> the token stored once it has run
        self.current = "OLD"
        claude._find_cli = lambda: "/usr/bin/claude"
        claude._run_briefly = self.run_briefly
        claude.token = lambda: (self.current, None) if self.current else (None, "token expired")

    def tearDown(self):
        claude._find_cli, claude._run_briefly, claude.token = self.saved

    def run_briefly(self, argv, limit):
        step = "prompt" if "-p" in argv else "status"
        self.ran.append(step)
        self.current = self.stored.get(step, self.current)
        return True

    def test_an_expired_token_is_done_once_status_renews_it(self):
        self.current = None
        self.stored = {"status": "NEW"}
        self.assertIsNone(claude.renew())
        self.assertEqual(self.ran, ["status"])

    def test_a_refused_token_still_on_disk_is_not_taken_as_renewed(self):
        # The refused token has not expired, so a plain validity check would
        # pass straight after the status call without anything having changed.
        self.stored = {"prompt": "NEW"}
        self.assertIsNone(claude.renew(rejected="OLD"))
        self.assertEqual(self.ran, ["status", "prompt"])

    def test_a_refused_token_that_never_changes_fails(self):
        self.assertEqual(claude.renew(rejected="OLD"), "renew failed")
        self.assertEqual(self.ran, ["status", "prompt"])


if __name__ == "__main__":
    unittest.main()
