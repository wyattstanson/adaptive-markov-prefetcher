"""Policy engine -- the phase -> (eviction rule, prefetch decision) mapping.

This is the twist the deck argues for: rather than committing to one eviction
rule for the whole run, the engine reads the detected phase and picks both the
rule to evict by and whether to prefetch at all. Restraint is deliberate --
prefetching during a random or thrashing phase evicts useful pages to make room
for guesses that will not hit, so it is switched off there.

    Phase        Evict   Prefetch
    ---------    -----   --------------------------------
    SEQUENTIAL   FIFO    aggressive (fetch several ahead)
    LOOPING      MRU     enabled (protect the loop, fetch head)
    RANDOM       LRU     suppressed (no structure to exploit)
    WARMUP       LRU     suppressed (nothing learned yet)

The engine is pure policy: it holds no cache state and makes no mechanism
decisions, which keeps it trivially inspectable and swappable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .phase import Phase


class Evict(str, Enum):
    FIFO = "fifo"
    LRU = "lru"
    MRU = "mru"


@dataclass(frozen=True)
class Plan:
    """The action the engine prescribes for the current phase."""

    evict: Evict
    prefetch: bool
    prefetch_degree: int


class PolicyEngine:
    def __init__(self, seq_degree: int = 4, loop_degree: int = 2) -> None:
        self.seq_degree = seq_degree
        self.loop_degree = loop_degree

    def plan(self, phase: Phase) -> Plan:
        if phase is Phase.SEQUENTIAL:
            return Plan(Evict.FIFO, prefetch=True, prefetch_degree=self.seq_degree)
        if phase is Phase.LOOPING:
            return Plan(Evict.MRU, prefetch=True, prefetch_degree=self.loop_degree)
        # RANDOM and WARMUP: react with LRU, do not speculate.
        return Plan(Evict.LRU, prefetch=False, prefetch_degree=0)
