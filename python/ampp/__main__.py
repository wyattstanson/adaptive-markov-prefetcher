"""Command-line entry point: run the benchmark and print/write the report.

    python -m ampp                 # print the results table
    python -m ampp --json out.json # also write the machine-readable report
"""

from __future__ import annotations

import argparse
import sys

from .benchmark import DEFAULT_CAPACITY, DEFAULT_LENGTH, DEFAULT_SEED, run_benchmark


def _print_table(report) -> None:
    for wl in report.workloads:
        print(f"\n{wl.workload.upper()}  (cache={wl.capacity}, accesses={wl.length}, seed={wl.seed})")
        print(f"  {'policy':<8} {'hit rate':>10} {'faults':>9} {'vs LRU':>10} {'prefetch acc':>13}")
        print("  " + "-" * 54)
        for r in wl.results:
            vs = "--" if r.policy == "LRU" else f"{r.fault_reduction_vs_lru * 100:6.1f}%"
            acc = f"{r.prefetch_accuracy * 100:5.1f}%" if r.prefetches else "   --"
            print(
                f"  {r.policy:<8} {r.hit_rate * 100:9.1f}% {r.faults:>9} {vs:>10} {acc:>13}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ampp", description="AMPP benchmark harness")
    parser.add_argument("--capacity", type=int, default=DEFAULT_CAPACITY)
    parser.add_argument("--length", type=int, default=DEFAULT_LENGTH)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--json", metavar="PATH", help="write the JSON report to PATH")
    args = parser.parse_args(argv)

    report = run_benchmark(capacity=args.capacity, length=args.length, seed=args.seed)
    _print_table(report)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(report.to_json())
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
