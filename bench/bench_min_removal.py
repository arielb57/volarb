"""Time min_removal (DP) against brute-force subset enumeration.

Usage: python bench/bench_min_removal.py [--quick]

Grids are Black-76 slices rounded to cents with 5% multiplicative noise, so
they carry a realistic handful of violations. Brute force enumerates subsets
from largest to smallest and stops at the first arbitrage-free one, so its cost
grows with both n and the size of the removal set.
"""

from __future__ import annotations

import argparse
import platform
import random
import statistics
import sys
import time
from fractions import Fraction

from volarb import Expiry, Quote, brute_force_min_removal, min_removal
from volarb.black import black76_call


def noisy_grid(rng: random.Random, n: int, noise: float = 0.05) -> Expiry:
    strikes = sorted(rng.sample(range(50 * 4, 150 * 4), n))
    quotes = []
    for row, s in enumerate(strikes):
        k = s / 4
        c = black76_call(100.0, k, 0.5, 0.25, 0.99) * (1 + rng.uniform(-noise, noise))
        quotes.append(Quote(Fraction(s, 4), Fraction(round(c * 100), 100), row))
    return Expiry("B", Fraction(1, 2), Fraction(100), Fraction("0.99"), tuple(quotes))


def exact_convex_grid(n: int) -> Expiry:
    # C(K) = DF * F^2 / (F + K): strictly convex, decreasing, slope in (-DF, 0), inside bounds.
    forward, discount = Fraction(100), Fraction("0.99")
    quotes = []
    for row in range(n):
        k = Fraction(50) + Fraction(100 * row, n)
        quotes.append(Quote(k, discount * forward**2 / (forward + k), row))
    return Expiry("W", Fraction(1, 2), forward, discount, tuple(quotes))


def timed(fn, *args):
    start = time.perf_counter()
    result = fn(*args)
    return time.perf_counter() - start, result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="fewer repeats, n up to 16")
    args = parser.parse_args()
    rng = random.Random(42)
    repeats = 1 if args.quick else 3
    top = 16 if args.quick else 20

    print(f"python {sys.version.split()[0]} on {platform.machine()} {platform.system()}")
    print()
    print("| n | removed (median) | DP median | brute force median | ratio |")
    print("|---|---|---|---|---|")
    for n in range(8, top + 1):
        dp_times, bf_times, removed = [], [], []
        for _ in range(repeats):
            grid = noisy_grid(rng, n)
            t_dp, a = timed(min_removal, grid)
            t_bf, b = timed(brute_force_min_removal, grid)
            assert len(a.removed) == len(b.removed)
            dp_times.append(t_dp)
            bf_times.append(t_bf)
            removed.append(len(a.removed))
        dp, bf = statistics.median(dp_times), statistics.median(bf_times)
        print(
            f"| {n} | {statistics.median(removed):g} | {dp * 1e3:.2f} ms "
            f"| {bf * 1e3:.1f} ms | {bf / dp:,.0f}x |"
        )

    print()
    print("| n | grid | removed | DP time |")
    print("|---|---|---|---|")
    for n in (50, 100, 200):
        grid = noisy_grid(rng, n, noise=0.02)
        t, r = timed(min_removal, grid)
        print(f"| {n} | 2% noise, cents | {len(r.removed)} | {t * 1e3:.0f} ms |")
        # Unrounded convex prices: every pair is a feasible edge, the DP's worst case.
        grid = exact_convex_grid(n)
        t, r = timed(min_removal, grid)
        print(f"| {n} | arbitrage-free, all edges feasible | {len(r.removed)} | {t * 1e3:.0f} ms |")


if __name__ == "__main__":
    main()
