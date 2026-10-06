"""Tests for the order-2 Markov predictor, including the order-2 vs order-1 point."""

from ampp.markov import Order2Markov


def test_no_prediction_before_learning():
    m = Order2Markov()
    assert m.predict() == []  # nothing observed yet
    m.observe(1)
    m.observe(2)
    # Pair (1,2) has never had a successor recorded.
    assert m.predict() == []


def test_learns_and_predicts_successor():
    m = Order2Markov()
    for _ in range(3):
        for p in [1, 2, 3]:
            m.observe(p)
    # State ends at (2,3); (2,3)->1 was seen, and (1,2)->3, (3,1)->2.
    m.observe(1)
    m.observe(2)
    assert m.predict() == [3]
    assert m.confidence() == 1.0


def test_order2_disambiguates_shared_middle_page():
    # The A->B->D vs C->B->E case: order-1 would collapse both onto B.
    m = Order2Markov()
    a, b, c, d, e = 10, 20, 30, 40, 50
    seq = [a, b, d, c, b, e] * 20
    for p in seq:
        m.observe(p)

    # Drive the state to (a, b) and confirm it predicts d, not e.
    m2 = Order2Markov()
    for p in seq:
        m2.observe(p)
    m2.observe(a)
    m2.observe(b)
    assert m2.predict() == [d]

    # Now drive to (c, b) and confirm it predicts e.
    m3 = Order2Markov()
    for p in seq:
        m3.observe(p)
    m3.observe(c)
    m3.observe(b)
    assert m3.predict() == [e]


def test_confidence_is_low_under_uniform_successors():
    m = Order2Markov()
    # From pair (1,2) send four different successors equally often.
    for nxt in [3, 4, 5, 6] * 25:
        m.observe(1)
        m.observe(2)
        m.observe(nxt)
    m.observe(1)
    m.observe(2)
    assert m.confidence() <= 0.35  # ~0.25, no dominant successor to prefetch
