"""Token counts from the agents' own session logs.

A provider's extract() turns one log line into
    (epoch, model, dedup_key, inp, out, cache_read, cache_write)
or None, and the Scanner here does the rest. It keeps byte offsets in memory,
so the first sweep costs about a second and every later one is effectively
free. Nothing is cached to disk, so the numbers can never drift out of sync
with a stale cache file.
"""
from __future__ import annotations

import glob
import os
import time
from datetime import date, timedelta

# Only the last 7 days are ever reported; the extra day absorbs timezone skew.
WINDOW_DAYS = 8

# How much of a file's start is remembered to tell it from a replacement that
# was given the same inode. One line of either log is well under this.
_HEAD_BYTES = 512

FIELDS = ("inp", "out", "cache_read", "cache_write")


def zero():
    return {"inp": 0, "out": 0, "cache_read": 0, "cache_write": 0, "reqs": 0}


def _add(dst, inp, out, cread, cwrite):
    dst["inp"] += inp
    dst["out"] += out
    dst["cache_read"] += cread
    dst["cache_write"] += cwrite
    dst["reqs"] += 1


def total_tokens(t):
    return t["inp"] + t["out"] + t["cache_read"] + t["cache_write"]


def _recent(path, cutoff):
    try:
        return os.path.getmtime(path) >= cutoff
    except OSError:
        return False


class Scanner:
    """Incrementally scan append-only jsonl logs into per-day, per-model totals."""

    def __init__(self, pattern, extract):
        self.pattern = pattern
        self.extract = extract
        self.offsets = {}  # path -> bytes already consumed
        self.seen = {}  # day -> set of dedup keys (resume/fork replays old history)
        self.days = {}  # 'YYYY-MM-DD' -> model -> totals

    def scan(self):
        cutoff = time.time() - WINDOW_DAYS * 86400
        for path in glob.iglob(self.pattern, recursive=True):
            try:
                st = os.stat(path)
            except OSError:
                continue
            # An mtime older than the window means every record inside is older too.
            if st.st_mtime < cutoff:
                continue
            ident = (st.st_dev, st.st_ino)
            prev_ident, prev_head, off = self.offsets.get(path, (None, None, 0))
            # Size cannot tell an append from a file replaced in place: a
            # rewrite to the same size or larger would be resumed from the
            # middle and stay misaligned for good. The inode usually settles
            # it, but a replacement can be handed the inode the old file just
            # released, so the first bytes are remembered too. They do not
            # change on an append and almost never survive a rewrite.
            if prev_ident != ident or st.st_size < off:
                off = 0
            if st.st_size == off:
                continue
            try:
                self._read(path, ident, prev_head, off, cutoff)
            except OSError:
                continue
        self._prune(cutoff)
        return self.days

    def _read(self, path, ident, prev_head, off, cutoff):
        with open(path, "rb") as fh:
            head = fh.read(_HEAD_BYTES)
            if off and (head != prev_head or not self._resumes_cleanly(fh, off)):
                off = 0
            fh.seek(off)
            pos = off
            for raw in fh:
                if not raw.endswith(b"\n"):
                    break  # half-written line; pick it up next sweep
                pos += len(raw)
                try:
                    rec = self.extract(raw)
                except Exception:
                    # A log is someone else's file and may hold anything. pos is
                    # already past this line, so skipping it here drops one
                    # record instead of freezing every later sweep on it.
                    continue
                if rec is None:
                    continue
                epoch, model, key, inp, out, cread, cwrite = rec
                if epoch < cutoff:
                    continue
                day = date.fromtimestamp(epoch).isoformat()
                if key is not None:
                    # Duplicates carry the same timestamp, hence the same day, so
                    # bucketing the dedup set by day still catches every repeat
                    # while letting old keys age out.
                    bucket = self.seen.setdefault(day, set())
                    if key in bucket:
                        continue
                    bucket.add(key)
                _add(self.days.setdefault(day, {}).setdefault(model, zero()),
                     inp, out, cread, cwrite)
            self.offsets[path] = (ident, head, pos)

    @staticmethod
    def _resumes_cleanly(fh, off):
        """True when byte off-1 is a newline, so off really is a line boundary."""
        try:
            fh.seek(off - 1)
            return fh.read(1) == b"\n"
        except OSError:
            return False

    def _prune(self, cutoff):
        keep = date.fromtimestamp(cutoff).isoformat()
        for day in [d for d in self.days if d < keep]:
            del self.days[day]
        for day in [d for d in self.seen if d < keep]:
            del self.seen[day]
        # Files that fell out of the window are never read again; drop their offsets.
        for path in [p for p in self.offsets if not _recent(p, cutoff)]:
            del self.offsets[path]


def summarize(days):
    """days -> {'today': {...}, 'week': {...}} with totals and a per-model split."""
    today = date.today()
    week_start = (today - timedelta(days=6)).isoformat()
    today_s = today.isoformat()

    out = {}
    for label, keep in (("today", lambda d: d == today_s), ("week", lambda d: d >= week_start)):
        total = zero()
        by_model = {}
        for day, models in days.items():
            if not keep(day):
                continue
            for model, t in models.items():
                acc = by_model.setdefault(model, zero())
                for f in FIELDS:
                    acc[f] += t[f]
                    total[f] += t[f]
                acc["reqs"] += t["reqs"]
                total["reqs"] += t["reqs"]
        out[label] = {"total": total, "by_model": by_model}
    return out
