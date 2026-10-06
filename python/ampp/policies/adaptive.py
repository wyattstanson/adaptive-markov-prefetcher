"""AdaptiveMarkovPrefetcher -- the policy this project contributes.

It composes the three stages rather than hard-coding one rule:

    phase detector  reads the live stream -> sequential | random | looping
    policy engine   maps the phase -> (eviction discipline, prefetch decision)
    order-2 Markov  supplies the pages to prefetch when the engine allows it

The eviction disciplines FIFO / LRU / MRU share one resident set; the frame
manager below implements all three so the engine can switch between them per
phase without the cache knowing which is active.

Pressure-aware gating has two guards, both meaning "don't speculate blindly":
  * the engine suppresses prefetch entirely in the random/warmup phase, and
  * even when enabled, a prefetch is only issued when the Markov model is
    confident about the successor (`confidence >= min_confidence`), so learned
    noise never evicts a useful page for a guess that will not hit.
"""

from __future__ import annotations

from collections import OrderedDict, deque

from ..engine import Evict, PolicyEngine
from ..markov import Order2Markov
from ..phase import PhaseDetector
from .base import ReplacementPolicy


class _Frames:
    """A resident page set supporting FIFO, LRU and MRU eviction.

    Recency order (for LRU/MRU) is kept in an OrderedDict updated on every touch;
    insertion order (for FIFO) is kept in a separate queue that hits do not
    reorder. `protect` shields pages the caller must not lose this step -- the
    current demand page and anything just prefetched -- so a prefetch can never
    evict itself or the page being served.
    """

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._recency: OrderedDict[int, None] = OrderedDict()  # LRU front .. MRU back
        self._fifo: deque[int] = deque()  # insertion order, oldest at left

    def __contains__(self, page: int) -> bool:
        return page in self._recency

    def __len__(self) -> int:
        return len(self._recency)

    def keys(self) -> set[int]:
        return set(self._recency)

    def touch(self, page: int) -> None:
        self._recency.move_to_end(page)

    def load(self, page: int, evict: Evict, protect: set[int]) -> int | None:
        """Insert `page`, evicting one page by `evict` if full. Returns the victim."""
        if page in self._recency:
            self.touch(page)
            return None
        victim: int | None = None
        if len(self._recency) >= self.capacity:
            victim = self._choose_victim(evict, protect)
            if victim is None:
                return None  # everything resident is protected; cannot make room
            self._remove(victim)
        self._recency[page] = None
        self._recency.move_to_end(page)
        self._fifo.append(page)
        return victim

    def _remove(self, page: int) -> None:
        del self._recency[page]
        # _fifo is compacted lazily in _choose_victim; leave the stale entry.

    def _choose_victim(self, evict: Evict, protect: set[int]) -> int | None:
        if evict is Evict.FIFO:
            skipped: list[int] = []
            victim: int | None = None
            while self._fifo:
                cand = self._fifo.popleft()
                if cand not in self._recency:
                    continue  # stale: already evicted
                if cand in protect:
                    skipped.append(cand)
                    continue
                victim = cand
                break
            self._fifo.extendleft(reversed(skipped))  # restore protected, order kept
            return victim
        if evict is Evict.LRU:
            for cand in self._recency:  # front = least recently used
                if cand not in protect:
                    return cand
            return None
        # MRU: most recently used first
        for cand in reversed(self._recency):
            if cand not in protect:
                return cand
        return None


class AdaptiveMarkovPrefetcher(ReplacementPolicy):
    name = "AMPP"

    def __init__(
        self,
        capacity: int,
        *,
        min_confidence: float = 0.5,
        engine: PolicyEngine | None = None,
    ) -> None:
        super().__init__(capacity)
        self._frames = _Frames(capacity)
        self._markov = Order2Markov()
        self._phase = PhaseDetector(capacity)
        self._engine = engine or PolicyEngine()
        self._min_confidence = min_confidence
        self._from_prefetch: set[int] = set()  # resident pages awaiting first demand

    def access(self, page: int) -> bool:
        phase = self._phase.update(page)
        plan = self._engine.plan(phase)
        self._markov.observe(page)
        self.stats.phase_counts[phase.value] = self.stats.phase_counts.get(phase.value, 0) + 1

        # Demand reference.
        if page in self._frames:
            self._frames.touch(page)
            served_by_prefetch = page in self._from_prefetch
            self._from_prefetch.discard(page)
            self.stats.record(hit=True, from_prefetch=served_by_prefetch)
            hit = True
        else:
            self._frames.load(page, plan.evict, protect=set())
            self._from_prefetch.discard(page)  # now a demanded page, not speculative
            self.stats.record(hit=False)
            hit = False

        # Pressure-aware prefetch: only when the phase allows it and the model
        # is confident about the successor.
        if plan.prefetch and self._markov.confidence() >= self._min_confidence:
            protect = {page}
            for pred in self._markov.predict(plan.prefetch_degree):
                if pred in self._frames:
                    continue
                victim = self._frames.load(pred, plan.evict, protect=protect)
                if victim is None and len(self._frames) >= self.capacity:
                    break  # no room without evicting a protected page
                if victim is not None:
                    self._from_prefetch.discard(victim)
                self._from_prefetch.add(pred)
                self.stats.prefetches += 1
                protect.add(pred)

        return hit

    def resident(self) -> set[int]:
        return self._frames.keys()
