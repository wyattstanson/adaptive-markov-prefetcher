"""Replacement policies: the classical baselines and the adaptive contribution.

All satisfy the same `ReplacementPolicy` contract, so the harness drives them
identically and compares them fairly.
"""

from .base import ReplacementPolicy, Stats
from .lru import LRU
from .clock import CLOCK
from .arc import ARC
from .adaptive import AdaptiveMarkovPrefetcher

__all__ = [
    "ReplacementPolicy",
    "Stats",
    "LRU",
    "CLOCK",
    "ARC",
    "AdaptiveMarkovPrefetcher",
]
