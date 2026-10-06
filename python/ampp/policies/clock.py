"""CLOCK -- the second-chance approximation of LRU.

Frames sit in a circular buffer, each with a reference bit. A hit sets the bit.
On a fault the hand advances, clearing set bits (a "second chance") until it
finds a frame whose bit is already clear, which it evicts. This approximates
recency at a fraction of LRU's bookkeeping cost, and so inherits LRU's loop and
scan pathologies.
"""

from __future__ import annotations

from .base import ReplacementPolicy


class CLOCK(ReplacementPolicy):
    name = "CLOCK"

    def __init__(self, capacity: int) -> None:
        super().__init__(capacity)
        self._frames: list[int] = []  # page in each slot
        self._ref: list[bool] = []  # reference bit per slot
        self._pos: dict[int, int] = {}  # page -> slot index
        self._hand = 0

    def access(self, page: int) -> bool:
        slot = self._pos.get(page)
        if slot is not None:
            self._ref[slot] = True
            self.stats.record(hit=True)
            return True

        if len(self._frames) < self.capacity:
            self._pos[page] = len(self._frames)
            self._frames.append(page)
            self._ref.append(True)
        else:
            self._evict_and_place(page)
        self.stats.record(hit=False)
        return False

    def _evict_and_place(self, page: int) -> None:
        while True:
            if not self._ref[self._hand]:
                victim = self._frames[self._hand]
                del self._pos[victim]
                self._frames[self._hand] = page
                self._ref[self._hand] = True
                self._pos[page] = self._hand
                self._hand = (self._hand + 1) % self.capacity
                return
            self._ref[self._hand] = False  # give a second chance
            self._hand = (self._hand + 1) % self.capacity

    def resident(self) -> set[int]:
        return set(self._frames)
