from __future__ import annotations

import math
import random
from fractions import Fraction

from volarb.black import black76_call
from volarb.model import Expiry, Quote

F = Fraction


def make_expiry(pairs, forward=100, discount=1, label="E", t="1/2") -> Expiry:
    """Expiry from (strike, price) pairs given as ints/strings; rows are list positions."""
    quotes = tuple(Quote(F(k), F(c), i) for i, (k, c) in enumerate(pairs))
    return Expiry(label, F(t), F(forward), F(discount), quotes)


def random_rough_expiry(rng: random.Random, n: int) -> Expiry:
    """A small, messy grid: Black prices rounded to cents, then noise, zeros,
    duplicate strikes and out-of-bound prices mixed in at random."""
    forward = F(100)
    discount = F(rng.choice(["1", "0.99", "0.95"]))
    vol = rng.uniform(0.1, 0.6)
    strikes = sorted(rng.choice(range(60, 141, 5)) for _ in range(n))
    noise = rng.choice([0.0, 0.01, 0.05, 0.2])
    quotes = []
    for row, k in enumerate(strikes):
        c = black76_call(100.0, float(k), 0.5, vol, float(discount))
        c *= 1 + rng.uniform(-noise, noise)
        r = rng.random()
        if r < 0.05:
            c = 0.0
        elif r < 0.08:
            c = float(discount) * 100 + 1
        elif r < 0.11:
            c = max(float(discount) * (100 - k), 0) - 0.5
        quotes.append(Quote(F(k), F(round(c, 2)).limit_denominator(100), row))
    return Expiry("R", F(1, 2), forward, discount, tuple(quotes))


def isclose(a, b, rel=1e-12):
    return math.isclose(float(a), float(b), rel_tol=rel, abs_tol=1e-12)
