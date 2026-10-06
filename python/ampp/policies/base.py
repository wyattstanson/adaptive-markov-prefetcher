"""The replacement-policy interface and the counters common to every policy.

Every policy -- the classical baselines and the adaptive one -- is driven the
same way by the harness: feed it one page at a time via `access`, and it reports
whether that reference was a hit. This uniform contract is what lets the
benchmark swap policies without special-casing any of them, and is the reason
the adaptive policy can be compared honestly against LRU, CLOCK and ARC.

A policy owns its own resident set and whatever bookkeeping its algorithm needs
(recency order, reference bits, ghost lists). The only thing standardised is the
`Stats` it accumulates and the `access` entry point.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Stats:
    """Hit/fault accounting for a single policy over a single trace."""

    accesses: int = 0
    hits: int = 0
    faults: int = 0  # demand misses -- references not satisfied from the cache
    prefetches: int = 0  # pages speculatively loaded before being demanded
    prefetch_hits: int = 0  # demands satisfied by a page a prefetch had loaded
    phase_counts: dict[str, int] = field(default_factory=dict)

    @property
    def hit_rate(self) -> float:
        return self.hits / self.accesses if self.accesses else 0.0

    @property
    def fault_rate(self) -> float:
        return self.faults / self.accesses if self.accesses else 0.0

    @property
    def prefetch_accuracy(self) -> float:
        """Fraction of issued prefetches that were later demanded from cache."""
        return self.prefetch_hits / self.prefetches if self.prefetches else 0.0

    def record(self, *, hit: bool, from_prefetch: bool = False) -> None:
        self.accesses += 1
        if hit:
            self.hits += 1
            if from_prefetch:
                self.prefetch_hits += 1
        else:
            self.faults += 1


class ReplacementPolicy(ABC):
    """Base class for every page-replacement policy in the simulator."""

    #: Human-readable name used in reports and tests.
    name: str = "policy"

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self.stats = Stats()

    @abstractmethod
    def access(self, page: int) -> bool:
        """Reference `page`; return True on a cache hit, False on a fault.

        Implementations update `self.stats` for exactly one demand reference per
        call (prefetching policies may additionally load other pages, but those
        do not count as accesses).
        """

    @abstractmethod
    def resident(self) -> set[int]:
        """Return the set of pages currently held in frames (for inspection/tests)."""

    def run(self, trace: list[int]) -> Stats:
        """Replay a whole trace and return the accumulated stats."""
        for page in trace:
            self.access(page)
        return self.stats
