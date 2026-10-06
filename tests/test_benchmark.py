"""End-to-end tests: the adaptive policy reproduces the headline results.

These assertions are the honest guardrail on the deck's numbers -- if the
implementation stopped delivering the claimed gains (or started claiming a gain
on random, where none exists), they fail.
"""

from ampp import gen_trace
from ampp.benchmark import run_benchmark, run_workload
from ampp.policies import AdaptiveMarkovPrefetcher, LRU
from ampp.trace import Workload


def _result(workload_result, policy_name):
    return next(r for r in workload_result.results if r.policy == policy_name)


def test_trace_is_deterministic():
    a = gen_trace(Workload.RANDOM, length=5000, seed=7)
    b = gen_trace(Workload.RANDOM, length=5000, seed=7)
    c = gen_trace(Workload.RANDOM, length=5000, seed=8)
    assert a == b
    assert a != c


def test_sequential_scan_beats_lru_massively():
    wl = run_workload(Workload.SEQUENTIAL)
    ampp = _result(wl, "AMPP")
    lru = _result(wl, "LRU")
    assert lru.hit_rate < 0.01  # LRU flatlines on the repeating scan
    assert ampp.hit_rate > 0.95
    assert ampp.fault_reduction_vs_lru > 0.95


def test_looping_beats_lru_massively():
    wl = run_workload(Workload.LOOPING)
    ampp = _result(wl, "AMPP")
    assert _result(wl, "LRU").hit_rate < 0.01
    assert ampp.hit_rate > 0.98
    assert ampp.fault_reduction_vs_lru > 0.98


def test_random_admits_no_gain():
    # The honesty test: on uniform random access there is no structure, so the
    # adaptive policy must NOT beat LRU (and must not prefetch usefully).
    wl = run_workload(Workload.RANDOM)
    ampp = _result(wl, "AMPP")
    lru = _result(wl, "LRU")
    assert abs(ampp.hit_rate - lru.hit_rate) < 0.02
    assert ampp.fault_reduction_vs_lru < 0.02


def test_prefetch_is_suppressed_on_random():
    # Pressure-aware gating: no confident predictions -> essentially no prefetch.
    trace = gen_trace(Workload.RANDOM, length=20000, seed=1234)
    ampp = AdaptiveMarkovPrefetcher(100)
    ampp.run(trace)
    assert ampp.stats.prefetches < 0.01 * len(trace)


def test_mixed_gains_track_structure():
    wl = run_workload(Workload.MIXED)
    ampp = _result(wl, "AMPP")
    # 80% of the mixed trace is structured, so the gain should be large but not
    # near-total (the random fifth carries no exploitable pattern).
    assert 0.6 < ampp.fault_reduction_vs_lru < 0.95


def test_capacity_is_never_exceeded():
    trace = gen_trace(Workload.MIXED, length=20000, seed=1234)
    ampp = AdaptiveMarkovPrefetcher(100)
    ampp.run(trace)
    assert len(ampp.resident()) <= 100


def test_full_benchmark_shape():
    report = run_benchmark(length=5000)
    assert len(report.workloads) == 4
    for wl in report.workloads:
        assert len(wl.results) == 4  # LRU, CLOCK, ARC, AMPP
