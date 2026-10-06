"""Phase detector -- the workload-reading stage.

Programs move through recurring phases in which behaviour is stable and distinct
from neighbouring intervals. This detector classifies the live stream into one
of three phases from cheap sliding-window statistics, so the policy engine can
pick the eviction rule and prefetch decision that suit the current behaviour.

Two horizons are tracked, because one window cannot separate the cases:

    short window (default 32)   -- stride signal: are references stepping +1?
    footprint window (~4x cache) -- how many *distinct* pages are in play

The subtlety a single window misses: a loop read in order is *locally* stride-+1,
just like a long scan. What tells them apart is the footprint. A loop just over
the cache revisits a small set; a scan's footprint keeps growing. So:

    LOOPING     structured stride AND footprint small (<= ~1.5x cache)
    SEQUENTIAL  strong forward stride AND large/growing footprint
    RANDOM      neither -- many distinct pages, little stride, little revisit

LOOPING is tested before SEQUENTIAL precisely because a loop looks sequential up
close; the footprint is what breaks the tie.
"""

from __future__ import annotations

from collections import Counter, deque
from enum import Enum


class Phase(str, Enum):
    SEQUENTIAL = "sequential"
    RANDOM = "random"
    LOOPING = "looping"
    WARMUP = "warmup"  # not enough history yet to classify


class PhaseDetector:
    def __init__(
        self,
        cache_size: int,
        window: int = 32,
        seq_threshold: float = 0.7,
        loop_seq_threshold: float = 0.4,
        loop_footprint_factor: float = 1.5,
    ) -> None:
        self.cache_size = cache_size
        self.window = window
        self.seq_threshold = seq_threshold
        self.loop_seq_threshold = loop_seq_threshold
        self.loop_footprint = int(loop_footprint_factor * cache_size)
        self.footprint_horizon = max(4 * cache_size, 256)

        self._short: deque[int] = deque(maxlen=window)
        self._long: deque[int] = deque(maxlen=self.footprint_horizon)
        # Occurrence count per page inside the footprint window, so the number of
        # distinct pages is maintained in O(1) per access instead of rebuilt.
        self._long_counts: Counter[int] = Counter()
        self._last: int | None = None
        self._plus_one = 0  # count of +1 steps currently inside the short window
        self._step_flags: deque[bool] = deque(maxlen=window)

    def update(self, page: int) -> Phase:
        """Feed the next reference and return the phase now in effect."""
        if self._last is not None:
            is_plus_one = page - self._last == 1
            if len(self._step_flags) == self.window and self._step_flags[0]:
                self._plus_one -= 1
            self._step_flags.append(is_plus_one)
            if is_plus_one:
                self._plus_one += 1
        self._last = page
        self._short.append(page)
        if len(self._long) == self.footprint_horizon:
            oldest = self._long[0]
            self._long_counts[oldest] -= 1
            if self._long_counts[oldest] == 0:
                del self._long_counts[oldest]
        self._long.append(page)
        self._long_counts[page] += 1

        if len(self._short) < self.window:
            return Phase.WARMUP

        seq_ratio = self._plus_one / max(len(self._step_flags), 1)
        footprint = len(self._long_counts)

        if seq_ratio >= self.loop_seq_threshold and footprint <= self.loop_footprint:
            return Phase.LOOPING
        if seq_ratio >= self.seq_threshold:
            return Phase.SEQUENTIAL
        return Phase.RANDOM

    def metrics(self) -> dict[str, float]:
        """Current window statistics, for inspection and tests."""
        seq_ratio = self._plus_one / max(len(self._step_flags), 1)
        unique = len(set(self._short))
        return {
            "seq_ratio": seq_ratio,
            "unique_count": float(unique),
            "revisit_ratio": 1.0 - unique / max(len(self._short), 1),
            "footprint": float(len(self._long_counts)),
        }
