"""Adaptive Markov Page Prefetcher with Pressure-Aware Eviction (AMPP).

A page-replacement simulator that couples three ideas the classical literature
keeps separate: an order-2 Markov predictor over the reference stream, an online
workload-phase detector, and pressure-aware prefetch gating that switches the
eviction rule per phase and suppresses speculation when it would thrash.

The package is organised as a pipeline of independently inspectable, swappable
stages, mirroring the system architecture in the project deck:

    trace  ->  order-2 Markov  ->  phase detector  ->  policy engine  ->  cache

Public surface:
    Workload, gen_trace          -- deterministic, seeded reference streams
    ReplacementPolicy, Stats     -- the swappable policy interface
    LRU, CLOCK, ARC              -- classical baselines
    AdaptiveMarkovPrefetcher     -- the policy this project contributes
    Order2Markov                 -- the pattern-memory stage
    PhaseDetector, Phase         -- the workload-reading stage
    PolicyEngine                 -- the phase -> (evict, prefetch) mapping
    run_benchmark                -- same trace / size / seed across policies
"""

from .trace import Workload, gen_trace
from .policies import ReplacementPolicy, Stats, LRU, CLOCK, ARC, AdaptiveMarkovPrefetcher
from .markov import Order2Markov
from .phase import PhaseDetector, Phase
from .engine import PolicyEngine, Plan
from .benchmark import run_benchmark, BenchmarkResult

__all__ = [
    "Workload",
    "gen_trace",
    "ReplacementPolicy",
    "Stats",
    "LRU",
    "CLOCK",
    "ARC",
    "AdaptiveMarkovPrefetcher",
    "Order2Markov",
    "PhaseDetector",
    "Phase",
    "PolicyEngine",
    "Plan",
    "run_benchmark",
    "BenchmarkResult",
]

__version__ = "1.0.0"
