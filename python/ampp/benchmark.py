"""Benchmark harness.

Fair play, stated on the deck and enforced here: every policy sees the *same*
trace, the *same* cache size, and the *same* seed. The only variable is the
policy. Two headline metrics are reported per workload:

    hit_rate        hits / accesses
    fault_reduction (LRU_faults - policy_faults) / LRU_faults, versus LRU

Fault reduction is measured against LRU because LRU is the textbook default and
the resume line ("N% fewer page faults than LRU") is stated relative to it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from .policies import ARC, CLOCK, LRU, AdaptiveMarkovPrefetcher, ReplacementPolicy
from .trace import Workload, gen_trace

# Experimental setup from the deck.
DEFAULT_CAPACITY = 100
DEFAULT_LENGTH = 20_000
DEFAULT_SEED = 1234


def _policies(capacity: int) -> list[ReplacementPolicy]:
    return [
        LRU(capacity),
        CLOCK(capacity),
        ARC(capacity),
        AdaptiveMarkovPrefetcher(capacity),
    ]


@dataclass
class PolicyResult:
    policy: str
    hit_rate: float
    fault_rate: float
    faults: int
    prefetches: int
    prefetch_accuracy: float
    fault_reduction_vs_lru: float
    phase_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class WorkloadResult:
    workload: str
    capacity: int
    length: int
    seed: int
    results: list[PolicyResult]


@dataclass
class BenchmarkResult:
    capacity: int
    length: int
    seed: int
    workloads: list[WorkloadResult]

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(asdict(self), indent=indent)


def run_workload(
    workload: Workload | str,
    capacity: int = DEFAULT_CAPACITY,
    length: int = DEFAULT_LENGTH,
    seed: int = DEFAULT_SEED,
) -> WorkloadResult:
    workload = Workload(workload)
    trace = gen_trace(workload, length=length, seed=seed)

    raw: dict[str, ReplacementPolicy] = {}
    for policy in _policies(capacity):
        policy.run(trace)
        raw[policy.name] = policy

    lru_faults = raw["LRU"].stats.faults or 1  # guard against divide-by-zero
    results = []
    for name, policy in raw.items():
        s = policy.stats
        results.append(
            PolicyResult(
                policy=name,
                hit_rate=round(s.hit_rate, 4),
                fault_rate=round(s.fault_rate, 4),
                faults=s.faults,
                prefetches=s.prefetches,
                prefetch_accuracy=round(s.prefetch_accuracy, 4),
                fault_reduction_vs_lru=round((lru_faults - s.faults) / lru_faults, 4),
                phase_counts=dict(s.phase_counts),
            )
        )
    return WorkloadResult(
        workload=workload.value,
        capacity=capacity,
        length=length,
        seed=seed,
        results=results,
    )


def run_benchmark(
    capacity: int = DEFAULT_CAPACITY,
    length: int = DEFAULT_LENGTH,
    seed: int = DEFAULT_SEED,
) -> BenchmarkResult:
    workloads = [
        run_workload(w, capacity=capacity, length=length, seed=seed)
        for w in (Workload.SEQUENTIAL, Workload.RANDOM, Workload.LOOPING, Workload.MIXED)
    ]
    return BenchmarkResult(capacity=capacity, length=length, seed=seed, workloads=workloads)
