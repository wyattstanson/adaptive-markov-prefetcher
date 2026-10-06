"""Order-2 Markov predictor -- the pattern-memory stage.

The state is the *pair* of the two most recent pages, not a single page. On each
reference the transition (prev, curr) -> next is counted, and the most probable
successors of the current pair can be read back to prefetch.

Why order-2 beats order-1: the sequences A->B->D and C->B->E share the middle
page B. A first-order model conditions only on B and collapses both, guessing
one successor for two futures. Conditioning on the pair keeps (A,B) and (C,B)
apart, so each predicts its own successor. This is a learned model, updated
online; it carries no assumption of sequentiality, unlike a stride prefetcher.
"""

from __future__ import annotations

from collections import defaultdict


class Order2Markov:
    """Online order-2 transition model over a page-reference stream."""

    def __init__(self) -> None:
        # (prev, curr) -> {next_page: count}
        self._table: dict[tuple[int, int], dict[int, int]] = defaultdict(dict)
        self._prev: int | None = None
        self._curr: int | None = None

    def observe(self, page: int) -> None:
        """Feed the next reference, recording the transition into it."""
        if self._prev is not None and self._curr is not None:
            succ = self._table[(self._prev, self._curr)]
            succ[page] = succ.get(page, 0) + 1
        self._prev, self._curr = self._curr, page

    def predict(self, k: int = 1) -> list[int]:
        """Return up to `k` most probable successors of the current pair state.

        Empty when the current pair has never been seen (nothing learned yet),
        which is precisely how the first pass over a new pattern stays honest:
        no prediction, no prefetch, until structure has actually been observed.
        """
        if self._prev is None or self._curr is None:
            return []
        succ = self._table.get((self._prev, self._curr))
        if not succ:
            return []
        ranked = sorted(succ.items(), key=lambda kv: (-kv[1], kv[0]))
        return [page for page, _ in ranked[:k]]

    def confidence(self) -> float:
        """Probability mass of the single top successor of the current state.

        1.0 means the next page is fully determined by the last two (a scan or a
        loop); near 1/n means the successor is effectively uniform (random),
        which the caller uses to decide whether prefetching is worthwhile.
        """
        if self._prev is None or self._curr is None:
            return 0.0
        succ = self._table.get((self._prev, self._curr))
        if not succ:
            return 0.0
        total = sum(succ.values())
        return max(succ.values()) / total if total else 0.0

    @property
    def state(self) -> tuple[int | None, int | None]:
        return (self._prev, self._curr)

    def __len__(self) -> int:
        """Number of distinct pair-states learned (model footprint)."""
        return len(self._table)
