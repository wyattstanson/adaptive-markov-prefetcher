"""Tests for the phase detector, including the loop-vs-scan tie-break."""

from ampp.phase import Phase, PhaseDetector


def _classify_stream(stream, cache=100):
    det = PhaseDetector(cache)
    phase = Phase.WARMUP
    for p in stream:
        phase = det.update(p)
    return phase


def test_sequential_scan_detected():
    # Large forward scan: strong +1 stride, footprint keeps growing.
    assert _classify_stream(range(500)) is Phase.SEQUENTIAL


def test_looping_detected_despite_local_sequentiality():
    # A loop just over the cache is locally stride-+1 like a scan; the small
    # footprint is what marks it as looping.
    loop = [i % 120 for i in range(2000)]
    assert _classify_stream(loop) is Phase.LOOPING


def test_random_detected():
    import random

    rng = random.Random(0)
    stream = [rng.randrange(300) for _ in range(2000)]
    assert _classify_stream(stream) is Phase.RANDOM


def test_warmup_before_window_fills():
    det = PhaseDetector(100, window=32)
    last = Phase.WARMUP
    for i in range(20):  # fewer than the window
        last = det.update(i)
    assert last is Phase.WARMUP


def test_metrics_reported():
    det = PhaseDetector(100)
    for i in range(100):
        det.update(i)
    m = det.metrics()
    assert m["seq_ratio"] > 0.9  # a pure scan is almost all +1 steps
    assert "footprint" in m


def test_footprint_is_maintained_incrementally():
    # The O(1) distinct-page counter must agree with a full recount of the
    # footprint window after it has wrapped many times over mixed traffic.
    import random

    rng = random.Random(3)
    det = PhaseDetector(100)
    stream = [rng.randrange(700) for _ in range(3000)] + [i % 120 for i in range(1500)]
    for p in stream:
        det.update(p)
    window = stream[-det.footprint_horizon:]
    assert det.metrics()["footprint"] == len(set(window))
