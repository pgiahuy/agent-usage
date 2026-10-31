import _env  # noqa: F401  (must come first)

import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone

import scan
from providers import claude, kimi


def claude_line(msg_id, req_id, model="claude-opus-5-5", inp=10, out=20, cread=300, cwrite=40,
                when=None, kind="assistant"):
    ts = (when or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
    return json.dumps({
        "type": kind, "timestamp": ts, "requestId": req_id,
        "message": {"id": msg_id, "model": model, "usage": {
            "input_tokens": inp, "output_tokens": out,
            "cache_read_input_tokens": cread, "cache_creation_input_tokens": cwrite}},
    }) + "\n"


def kimi_line(scope="turn", ms=None, inp=5, out=7, cread=100, cwrite=0, model="k3"):
    return json.dumps({
        "type": "usage.record", "usageScope": scope, "model": model,
        "time": ms if ms is not None else int(time.time() * 1000),
        "usage": {"inputOther": inp, "output": out, "inputCacheRead": cread,
                  "inputCacheCreation": cwrite},
    }) + "\n"


class ExtractTest(unittest.TestCase):
    def test_claude_assistant_line(self):
        rec = claude.extract(claude_line("m1", "r1").encode())
        self.assertEqual(rec[1:], ("claude-opus-5-5", "m1|r1", 10, 20, 300, 40))

    def test_claude_ignores_other_lines(self):
        self.assertIsNone(claude.extract(claude_line("m", "r", kind="user").encode()))
        self.assertIsNone(claude.extract(claude_line("m", "r", model="<synthetic>").encode()))
        self.assertIsNone(claude.extract(b'{"type": "summary"}\n'))
        self.assertIsNone(claude.extract(b'not json "usage"\n'))

    def test_kimi_counts_turns_only(self):
        self.assertEqual(kimi.extract(kimi_line().encode())[3:], (5, 7, 100, 0))
        # A session record is a running total: counting it would double the sum.
        self.assertIsNone(kimi.extract(kimi_line(scope="session").encode()))


class ScannerTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(dir=_env.ROOT)
        self.path = os.path.join(self.dir, "a.jsonl")
        self.scanner = scan.Scanner(os.path.join(self.dir, "*.jsonl"), claude.extract)

    def append(self, text):
        with open(self.path, "a") as fh:
            fh.write(text)

    def today(self):
        return scan.summarize(self.scanner.scan())["today"]["total"]

    def test_incremental_and_deduplicated(self):
        self.append(claude_line("m1", "r1") + claude_line("m2", "r2"))
        self.assertEqual(self.today()["reqs"], 2)
        # A resumed session replays m1 into the log: it must not count twice.
        self.append(claude_line("m1", "r1") + claude_line("m3", "r3"))
        total = self.today()
        self.assertEqual(total["reqs"], 3)
        self.assertEqual(scan.total_tokens(total), 3 * (10 + 20 + 300 + 40))

    def test_half_written_line_waits(self):
        line = claude_line("m1", "r1")
        self.append(line[:30])
        self.assertEqual(self.today()["reqs"], 0)
        self.append(line[30:])
        self.assertEqual(self.today()["reqs"], 1)

    def test_old_records_fall_outside_the_window(self):
        old = datetime.fromtimestamp(time.time() - 30 * 86400, timezone.utc)
        self.append(claude_line("m1", "r1", when=old))
        summary = scan.summarize(self.scanner.scan())
        self.assertEqual(summary["week"]["total"]["reqs"], 0)

    def test_a_line_the_extractor_cannot_read_is_skipped_for_good(self):
        """A log belongs to another program and may hold anything.

        Each of these raises out of claude.extract: a JSON array, a numeric
        timestamp, a token count that is not a number. Before the guard the
        exception left the sweep, which both stopped state.json being written
        and left the offset uncommitted, so the same line broke every later
        pass as well.
        """
        self.append(claude_line("m1", "r1"))
        self.assertEqual(self.today()["reqs"], 1)
        for bad in ('["usage", 1]\n',
                    '{"type":"assistant","timestamp":1,"message":{"id":"x","usage":{}}}\n',
                    '{"type":"assistant","timestamp":"2026-10-01T00:00:00Z",'
                    '"message":{"id":"y","usage":{"input_tokens":"lots"}}}\n'):
            self.append(bad)
            self.assertEqual(self.today()["reqs"], 1)  # survived, nothing counted
        # Later good records still arrive, which is what the offset proves.
        self.append(claude_line("m2", "r2"))
        self.assertEqual(self.today()["reqs"], 2)

    def test_a_file_replaced_in_place_is_read_from_the_start(self):
        """Size cannot tell an append from a replacement.

        A rewrite to the same size or larger used to resume from the stored
        offset, so the first bytes read were half a line and every record in
        the new file was lost for good.
        """
        self.append(claude_line("m1", "r1") + claude_line("m2", "r2"))
        self.assertEqual(self.today()["reqs"], 2)
        os.remove(self.path)
        with open(self.path, "w") as fh:  # new inode, bigger than the old offset
            fh.write(claude_line("m3", "r3") + claude_line("m4", "r4")
                     + claude_line("m5", "r5"))
        self.assertEqual(self.today()["reqs"], 5)


if __name__ == "__main__":
    unittest.main()
