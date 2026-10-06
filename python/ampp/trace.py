"""Workload generators.

A trace is a list of page numbers -- the reference stream a process would issue.
Every generator is deterministic given a seed, so any policy can be replayed on
byte-identical input ("same trace, same cache size, same seed for every policy").

Four workload families, matching the experimental setup in the deck:

    sequential  a forward scan of `footprint` pages, repeated to fill the trace
    random      uniform draws over `footprint` pages (no exploitable structure)
    looping     a fixed loop of `footprint` pages, slightly larger than the cache
    mixed       the three above, interleaved in segments

The looping footprint is deliberately just over the cache size: that is the
regime where a recency policy evicts the very page it is about to need.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum


class Workload(str, Enum):
    """The four workload families the harness benchmarks against."""

    SEQUENTIAL = "sequential"
    RANDOM = "random"
    LOOPING = "looping"
    MIXED = "mixed"


@dataclass(frozen=True)
class TraceSpec:
    """A reproducible description of a trace: everything needed to regenerate it."""

    workload: Workload
    length: int
    footprint: int
    seed: int


def gen_trace(
    workload: Workload | str,
    length: int = 20_000,
    footprint: int | None = None,
    seed: int = 1234,
) -> list[int]:
    """Return a deterministic reference stream of `length` page numbers.

    `footprint` is the number of distinct pages the workload touches. When left
    as None it defaults to the value used in the deck for each family.
    """

    workload = Workload(workload)
    fp = footprint if footprint is not None else _DEFAULT_FOOTPRINT[workload]
    rng = random.Random(seed)

    if workload is Workload.SEQUENTIAL:
        return _sequential(length, fp)
    if workload is Workload.RANDOM:
        return _random(length, fp, rng)
    if workload is Workload.LOOPING:
        return _looping(length, fp)
    if workload is Workload.MIXED:
        return _mixed(length, rng)
    raise ValueError(f"unknown workload: {workload}")


_DEFAULT_FOOTPRINT: dict[Workload, int] = {
    Workload.SEQUENTIAL: 500,
    Workload.RANDOM: 300,
    Workload.LOOPING: 120,
    Workload.MIXED: 0,  # unused; mixed composes the others
}


def _sequential(length: int, footprint: int) -> list[int]:
    # A forward scan 0..footprint-1, repeated. Locally stride +1, large footprint.
    return [i % footprint for i in range(length)]


def _random(length: int, footprint: int, rng: random.Random) -> list[int]:
    # Uniform over the footprint. No temporal structure to learn or prefetch.
    return [rng.randrange(footprint) for _ in range(length)]


def _looping(length: int, footprint: int) -> list[int]:
    # A fixed loop whose footprint sits just over the cache: the loop trap.
    return [i % footprint for i in range(length)]


#: Phase schedule for the mixed workload. Structured phases (scans, loops)
#: dominate and random probing is the minority phase -- the realistic case, since
#: programs spend far more time streaming data and re-scanning working sets than
#: chasing uniformly random addresses. Random is 1 of 5 segments (20%). The gain
#: on this workload therefore tracks the fraction of the trace that carries
#: structure a predictor can exploit; it is not tuned to any target figure.
_MIXED_SCHEDULE = ("scan", "loop", "random", "scan", "loop")


def _mixed(length: int, rng: random.Random) -> list[int]:
    """Interleave scan, random and loop segments, offset into disjoint page ranges.

    Each family lives in its own page band so the phase detector sees genuine
    transitions between qualitatively different behaviours, not one blurred set.
    """

    scan_base, loop_base, rand_base = 0, 1_000, 2_000
    scan_fp, loop_fp, rand_fp = 500, 120, 300
    segment = 1_000
    out: list[int] = []
    step = 0
    while len(out) < length:
        n = min(segment, length - len(out))
        kind = _MIXED_SCHEDULE[step % len(_MIXED_SCHEDULE)]
        if kind == "scan":
            out += [scan_base + (i % scan_fp) for i in range(n)]
        elif kind == "loop":
            out += [loop_base + (i % loop_fp) for i in range(n)]
        else:  # random
            out += [rand_base + rng.randrange(rand_fp) for _ in range(n)]
        step += 1
    return out[:length]
