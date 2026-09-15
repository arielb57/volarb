"""Violations found in naive SVI slices that break the Gatheral–Jacquier condition.

Usage: python bench/svi_gj_table.py

Each slice is priced with Black-76 on 61 strikes, log-moneyness evenly spaced
in [-1.5, 1.5], F = 100, DF = 1, T = 1. Naive slices are sampled with no
butterfly constraint and kept when min g < 0 on [-1.5, 1.5]; one GJ-compliant
slice is shown for contrast.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from fractions import Fraction

from volarb import check_expiry, min_removal
from volarb.synth import VOGT, SviParams, random_svi, svi_expiry

K_LO, K_HI, N = -1.5, 1.5, 61
NOISE = Fraction(1, 10**12)


def strikes() -> list[Fraction]:
    grid = []
    for i in range(N):
        k = K_LO + (K_HI - K_LO) * i / (N - 1)
        grid.append(Fraction(round(100 * math.exp(k) * 100), 100))
    return grid


def row(name: str, p: SviParams) -> str:
    e = svi_expiry(name, Fraction(1), Fraction(100), Fraction(1), p, strikes())
    vs = check_expiry(e)
    # Violations this small come from float rounding in Black-76, not from the smile.
    tiny = sum(1 for v in vs if v.size < NOISE)
    vs = [v for v in vs if v.size >= NOISE]
    counts = Counter(v.kind.value for v in vs)
    flagged = sorted({r.row for v in vs for r in v.quotes})
    span = "-"
    if flagged:
        ks = [math.log(e.quotes[i].strike / 100) for i in flagged]
        span = f"{min(ks):+.2f} .. {max(ks):+.2f}"
    removed = len(min_removal(e).removed)
    params = f"{p.a:.4f}, {p.b:.4f}, {p.rho:+.3f}, {p.m:+.3f}, {p.sigma:.3f}"
    other = len(vs) - counts["convexity"] - counts["monotonicity"]
    return (
        f"| {name} | {params} | {p.min_g(K_LO, K_HI):+.4f} | {counts['convexity']} "
        f"| {counts['monotonicity']} | {other} | {tiny} | {span} | {removed} |"
    )


def main() -> None:
    print(
        "| slice | a, b, rho, m, sigma | min g | convexity | monotonicity | other "
        "| size < 1e-12 | flagged k range | min removal (of 61) |"
    )
    print("|---|---|---|---|---|---|---|---|---|")
    print(row("Vogt", VOGT))
    rng = random.Random(7)
    shown = 0
    while shown < 6:
        p = random_svi(rng, K_LO, K_HI, gj=False)
        if p.min_g(K_LO, K_HI) < 0:
            shown += 1
            print(row(f"naive-{shown}", p))
    print(row("GJ-ok", random_svi(random.Random(1), K_LO, K_HI)))


if __name__ == "__main__":
    main()
