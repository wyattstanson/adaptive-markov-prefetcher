"""Correctness and pathology tests for the classical baselines."""

from ampp.policies import ARC, CLOCK, LRU


def test_lru_hits_within_capacity():
    lru = LRU(3)
    for p in [1, 2, 3, 1, 2, 3]:
        lru.access(p)
    # First three are compulsory misses; the repeats all hit.
    assert lru.stats.faults == 3
    assert lru.stats.hits == 3
    assert lru.resident() == {1, 2, 3}


def test_lru_loop_pathology_is_total():
    # A loop one page larger than the cache: LRU evicts the page needed next,
    # so every single reference faults. This is the pathology the project beats.
    cap = 50
    loop = [i % (cap + 1) for i in range(5000)]
    lru = LRU(cap)
    lru.run(loop)
    assert lru.stats.hits == 0
    assert lru.stats.hit_rate == 0.0


def test_clock_never_exceeds_capacity_and_matches_lru_order_of_magnitude():
    cap = 16
    loop = [i % (cap + 1) for i in range(3000)]
    clock = CLOCK(cap)
    clock.run(loop)
    assert len(clock.resident()) <= cap
    # CLOCK approximates LRU, so it inherits the same loop pathology.
    assert clock.stats.hit_rate == 0.0


def test_clock_reference_bit_gives_second_chance():
    # Second chance protects a re-referenced page over an untouched neighbour.
    clock = CLOCK(3)
    for p in [1, 2, 3]:
        clock.access(p)
    clock.access(4)  # sweeps, evicts 1; leaves 3's bit clear, 4's set
    clock.access(2)  # re-reference 2 -> sets its bit (its second chance)
    clock.access(5)  # 2 is skipped (bit set), 3 is evicted (bit clear)
    assert 2 in clock.resident()  # survived because it was re-referenced
    assert 3 not in clock.resident()  # evicted: never touched again
    assert len(clock.resident()) == 3


def test_arc_respects_capacity_and_is_scan_resistant():
    cap = 100
    # A hot working set repeatedly touched, with a long one-shot scan through it.
    hot = list(range(10)) * 50
    scan = list(range(1000, 3000))
    trace = hot + scan + list(range(10)) * 20
    arc = ARC(cap)
    arc.run(trace)
    assert len(arc.resident()) <= cap
    # After the scan, the hot pages should mostly survive (scan resistance):
    # the trailing re-touches of 0..9 should largely hit, unlike pure LRU.
    lru = LRU(cap)
    lru.run(trace)
    assert arc.stats.hits >= lru.stats.hits


def test_arc_loop_pathology_like_recency():
    # ARC adapts along recency<->frequency but never prefetches, so a loop just
    # over the cache still defeats it.
    cap = 100
    loop = [i % (cap + 20) for i in range(20000)]
    arc = ARC(cap)
    arc.run(loop)
    assert arc.stats.hit_rate < 0.05
