"""Least Recently Used -- the canonical recency baseline.

Evicts the page unused for the longest time, on the assumption that recent use
predicts future use. Captures temporal locality well, but on a loop slightly
larger than the cache it evicts the exact page needed next and faults on every
reference -- the pathology this project sets out to beat.
"""

from __future__ import annotations

from collections import OrderedDict

from .base import ReplacementPolicy


class LRU(ReplacementPolicy):
    name = "LRU"

    def __init__(self, capacity: int) -> None:
        super().__init__(capacity)
        self._frames: OrderedDict[int, None] = OrderedDict()

    def access(self, page: int) -> bool:
        if page in self._frames:
            self._frames.move_to_end(page)  # most-recently-used end
            self.stats.record(hit=True)
            return True
        if len(self._frames) >= self.capacity:
            self._frames.popitem(last=False)  # evict least-recently-used
        self._frames[page] = None
        self.stats.record(hit=False)
        return False

    def resident(self) -> set[int]:
        return set(self._frames)
