"""ARC -- Adaptive Replacement Cache (Megiddo & Modha, FAST 2003).

The strongest classical baseline in this study. ARC keeps two resident lists --
T1 for pages seen once, T2 for pages seen more than once -- plus two ghost lists
B1/B2 that remember recently evicted pages. Hits on ghosts continuously retune
the target boundary `p` between recency and frequency, so ARC self-adjusts
without manual parameters and is scan-resistant.

It is, however, purely reactive: it adapts *which* page to evict along a single
recency<->frequency axis, and never prefetches. That is exactly the boundary the
adaptive policy in this project steps past.

This is the full algorithm from the paper, not a simplification.
"""

from __future__ import annotations

from collections import OrderedDict

from .base import ReplacementPolicy


class _LRUList:
    """An ordered set with O(1) LRU/MRU access, backed by an OrderedDict."""

    def __init__(self) -> None:
        self._d: OrderedDict[int, None] = OrderedDict()

    def __contains__(self, x: int) -> bool:
        return x in self._d

    def __len__(self) -> int:
        return len(self._d)

    def push_mru(self, x: int) -> None:
        self._d[x] = None
        self._d.move_to_end(x)

    def pop_lru(self) -> int:
        x, _ = self._d.popitem(last=False)
        return x

    def lru(self) -> int:
        return next(iter(self._d))

    def remove(self, x: int) -> None:
        del self._d[x]

    def keys(self) -> set[int]:
        return set(self._d)


class ARC(ReplacementPolicy):
    name = "ARC"

    def __init__(self, capacity: int) -> None:
        super().__init__(capacity)
        self.c = capacity
        self.p = 0  # adaptive target size for T1
        self.t1 = _LRUList()
        self.t2 = _LRUList()
        self.b1 = _LRUList()
        self.b2 = _LRUList()

    def access(self, page: int) -> bool:
        x = page

        # Case I -- resident hit: promote to the frequency list.
        if x in self.t1:
            self.t1.remove(x)
            self.t2.push_mru(x)
            self.stats.record(hit=True)
            return True
        if x in self.t2:
            self.t2.remove(x)
            self.t2.push_mru(x)
            self.stats.record(hit=True)
            return True

        # Case II -- hit in B1 ghost: bias toward recency.
        if x in self.b1:
            delta = max(len(self.b2) / len(self.b1), 1) if len(self.b1) else 1
            self.p = min(self.p + delta, self.c)
            self._replace(x)
            self.b1.remove(x)
            self.t2.push_mru(x)
            self.stats.record(hit=False)
            return False

        # Case III -- hit in B2 ghost: bias toward frequency.
        if x in self.b2:
            delta = max(len(self.b1) / len(self.b2), 1) if len(self.b2) else 1
            self.p = max(self.p - delta, 0)
            self._replace(x)
            self.b2.remove(x)
            self.t2.push_mru(x)
            self.stats.record(hit=False)
            return False

        # Case IV -- genuine miss, page seen in none of the four lists.
        l1 = len(self.t1) + len(self.b1)
        if l1 == self.c:
            if len(self.t1) < self.c:
                self.b1.pop_lru()
                self._replace(x)
            else:
                self.t1.pop_lru()  # B1 empty; evict a real page from T1
        else:
            total = len(self.t1) + len(self.t2) + len(self.b1) + len(self.b2)
            if total >= self.c:
                if total == 2 * self.c:
                    self.b2.pop_lru()
                self._replace(x)

        self.t1.push_mru(x)
        self.stats.record(hit=False)
        return False

    def _replace(self, x: int) -> None:
        """Evict one resident page, moving it to the matching ghost list."""
        if len(self.t1) >= 1 and (
            (x in self.b2 and len(self.t1) == self.p) or len(self.t1) > self.p
        ):
            victim = self.t1.pop_lru()
            self.b1.push_mru(victim)
        else:
            victim = self.t2.pop_lru()
            self.b2.push_mru(victim)

    def resident(self) -> set[int]:
        return self.t1.keys() | self.t2.keys()
