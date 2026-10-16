"""Token counts per provider, with the scanners kept alive between passes."""
from __future__ import annotations

import scan
from providers import PROVIDERS


class Collector:
    """Holds one Scanner per provider so each pass reads only new bytes."""

    def __init__(self, providers=PROVIDERS):
        self._scanners = {p.tag: scan.Scanner(p.log_glob, p.extract) for p in providers}

    def local(self, providers):
        # A provider left out keeps its offsets, so once it is back the next
        # pass reads everything written in between and no tokens go missing.
        return {p.tag: scan.summarize(self._scanners[p.tag].scan()) for p in providers}
