"""SVI-parameterised synthetic surfaces, and exact arbitrage injection."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, replace
from fractions import Fraction

from .black import call_price_from_vol
from .checks import lower_bound, upper_bound
from .model import Expiry, Quote, Surface


@dataclass(frozen=True)
class SviParams:
    """Raw SVI: w(k) = a + b*(rho*(k-m) + sqrt((k-m)^2 + sigma^2)), k = log(K/F)."""

    a: float
    b: float
    rho: float
    m: float
    sigma: float

    def total_variance(self, k: float) -> float:
        x = k - self.m
        return self.a + self.b * (self.rho * x + math.sqrt(x * x + self.sigma * self.sigma))

    def g(self, k: float) -> float:
        """Gatheral–Jacquier density factor; butterfly-free iff g >= 0 (and w > 0)."""
        x = k - self.m
        root = math.sqrt(x * x + self.sigma * self.sigma)
        w = self.total_variance(k)
        w1 = self.b * (self.rho + x / root)
        w2 = self.b * self.sigma * self.sigma / root**3
        return (1 - k * w1 / (2 * w)) ** 2 - (w1 * w1 / 4) * (1 / w + 0.25) + w2 / 2

    def min_g(self, k_lo: float, k_hi: float, samples: int = 2001) -> float:
        """Minimum of g on an even grid over [k_lo, k_hi]; -inf if w <= 0 anywhere there."""
        lowest = math.inf
        for i in range(samples):
            k = k_lo + (k_hi - k_lo) * i / (samples - 1)
            if self.total_variance(k) <= 0:
                return -math.inf
            lowest = min(lowest, self.g(k))
        return lowest

    def scaled(self, factor: float) -> SviParams:
        return replace(self, a=self.a * factor, b=self.b * factor)


# Axel Vogt's parameters (T = 1), the counterexample in Gatheral & Jacquier (2014):
# positive total variance everywhere, yet negative density near k = 0.6.
GJ_RANGE = 8.0

VOGT = SviParams(a=-0.0410, b=0.1331, rho=0.3060, m=0.3586, sigma=0.4153)


def svi_expiry(
    label: str,
    t: Fraction,
    forward: Fraction,
    discount: Fraction,
    params: SviParams,
    strikes: Sequence[Fraction],
    first_row: int = 0,
) -> Expiry:
    """Price an SVI slice on the given strikes. Black-76 runs in float; results are
    stored as the exact binary value of each float."""
    quotes = []
    for i, strike in enumerate(strikes):
        w = params.total_variance(math.log(strike / forward))
        if w < 0:
            raise ValueError(f"negative total variance at K={strike}")
        vol = math.sqrt(w / float(t))
        price = call_price_from_vol(forward, strike, t, vol, discount)
        quotes.append(Quote(Fraction(strike), price, first_row + i))
    return Expiry(label, Fraction(t), Fraction(forward), Fraction(discount), tuple(quotes))


def random_svi(
    rng: random.Random,
    k_lo: float,
    k_hi: float,
    *,
    gj: bool = True,
    margin: float = 1e-3,
    scales: Sequence[float] = (1.0,),
    max_tries: int = 100_000,
) -> SviParams:
    """Sample raw SVI parameters with positive variance on [k_lo, k_hi].

    With ``gj=True`` every ``params.scaled(s)`` for s in ``scales`` must also
    satisfy min g >= margin on the whole of [-GJ_RANGE, GJ_RANGE] (not just the
    quoted range: negative density in an unquoted wing still makes the quotes
    inconsistent with C(0) = DF·F), and the wing slopes must obey
    b*(1+|rho|) < 2, which is where g stays non-negative as |k| grows.
    With ``gj=False`` no butterfly condition is imposed.
    """
    for _ in range(max_tries):
        p = SviParams(
            a=rng.uniform(-0.01, 0.03),
            b=rng.uniform(0.01, 0.25),
            rho=rng.uniform(-0.95, 0.95),
            m=rng.uniform(-0.3, 0.3),
            sigma=rng.uniform(0.02, 0.5),
        )
        if not gj:
            if all(p.scaled(s).min_g(k_lo, k_hi, 201) > -math.inf for s in scales):
                return p
            continue
        if all(
            p.b * s * (1 + abs(p.rho)) < 2
            and p.scaled(s).min_g(k_lo, k_hi, 201) >= margin
            and p.scaled(s).min_g(-GJ_RANGE, GJ_RANGE, 4001) >= margin
            for s in scales
        ):
            return p
    raise RuntimeError("could not sample SVI parameters")


def random_strikes(
    rng: random.Random,
    forward: Fraction,
    n: int,
    k_lo: float,
    k_hi: float,
    tick: Fraction = Fraction(1, 4),
) -> list[Fraction]:
    """n distinct strikes on a tick grid, log-moneyness uniform in [k_lo, k_hi]."""
    lo = math.ceil(float(forward) * math.exp(k_lo) / tick)
    hi = math.floor(float(forward) * math.exp(k_hi) / tick)
    if hi - lo + 1 < n:
        raise ValueError("strike range too narrow for the tick size")
    return sorted(i * tick for i in rng.sample(range(lo, hi + 1), n))


def synthetic_surface(
    rng: random.Random,
    *,
    n_expiries: int = 3,
    n_strikes: int = 15,
    spot: Fraction = Fraction(100),
    rate: float = 0.03,
    k_range: tuple[float, float] = (-0.4, 0.4),
    shared_moneyness: bool = False,
    gj: bool = True,
) -> Surface:
    """An SVI surface whose expiry i has total variance (i+1) * w(k).

    Scaling total variance up with maturity makes the surface calendar-free;
    with ``gj=True`` each slice also satisfies the Gatheral–Jacquier condition
    on ``k_range``. Forwards are spot / DF, i.e. zero dividends.
    """
    k_lo, k_hi = k_range
    scales = [float(i + 1) for i in range(n_expiries)]
    params = random_svi(rng, k_lo, k_hi, gj=gj, scales=scales)
    base_strikes = random_strikes(rng, spot, n_strikes, k_lo, k_hi)
    expiries = []
    row = 0
    for i, scale in enumerate(scales):
        t = Fraction(i + 1, 4)
        discount = Fraction(round(math.exp(-rate * float(t)), 6)).limit_denominator(10**6)
        forward = spot / discount
        if shared_moneyness:
            strikes = [k * forward / spot for k in base_strikes]
        else:
            strikes = random_strikes(rng, forward, n_strikes, k_lo, k_hi)
        label = f"T{i + 1}"
        expiries.append(svi_expiry(label, t, forward, discount, params.scaled(scale), strikes, row))
        row += n_strikes
    return Surface(tuple(expiries))


def _set_prices(expiry: Expiry, prices: dict[int, Fraction]) -> Expiry:
    quotes = [Quote(q.strike, prices.get(q.row, q.price), q.row) for q in expiry.quotes]
    return expiry.with_quotes(quotes)


def _distinct_strikes(expiry: Expiry) -> None:
    strikes = [q.strike for q in expiry.quotes]
    if len(set(strikes)) != len(strikes):
        raise ValueError("injection needs distinct strikes")


def inject_bump(
    surface: Surface, label: str, index: int, fraction: Fraction = Fraction(1, 2)
) -> Surface:
    """Raise quote ``index`` above the chord of its neighbours.

    The new price is chord + fraction * room, where room is the most it can
    rise without also breaking monotonicity or the vertical-spread bound. On
    an arbitrage-free slice this creates exactly one violation: convexity at
    (index-1, index, index+1).
    """
    e = surface.expiry(label)
    _distinct_strikes(e)
    if not 0 < index < len(e.quotes) - 1:
        raise ValueError("bump index must be an interior quote")
    if not 0 < fraction < 1:
        raise ValueError("fraction must be in (0, 1)")
    left, mid, right = e.quotes[index - 1], e.quotes[index], e.quotes[index + 1]
    w = (mid.strike - left.strike) / (right.strike - left.strike)
    chord = left.price + w * (right.price - left.price)
    ceiling = min(left.price, right.price + e.discount * (right.strike - mid.strike))
    room = ceiling - chord
    if room <= 0:
        raise ValueError("no room to bump without breaking monotonicity")
    return surface.replace(_set_prices(e, {mid.row: chord + fraction * room}))


def inject_tilt(surface: Surface, label: str, start: int, excess: Fraction) -> Surface:
    """Add a rising linear tilt to every quote from ``start`` onwards.

    The tilt slope is excess - s, where s is the slope between quotes start
    and start+1, so that spread and (on a convex slice) every later one slope
    upward by at least ``excess``: monotonicity violations on each pair from
    ``start`` on, and nothing else. Raises if a tilted price would breach DF·F.
    """
    e = surface.expiry(label)
    _distinct_strikes(e)
    if not 0 <= start < len(e.quotes) - 1:
        raise ValueError("tilt start must leave at least one quote after it")
    if excess <= 0:
        raise ValueError("excess must be positive")
    a, b = e.quotes[start], e.quotes[start + 1]
    alpha = excess - (b.price - a.price) / (b.strike - a.strike)
    prices = {q.row: q.price + alpha * (q.strike - a.strike) for q in e.quotes[start:]}
    if any(p > upper_bound(e) for p in prices.values()):
        raise ValueError("tilt would breach the upper bound DF*F")
    return surface.replace(_set_prices(e, prices))


def inject_calendar_crossing(
    surface: Surface, later_label: str, weight: Fraction = Fraction(1, 2)
) -> Surface:
    """Pull the later expiry below its predecessor.

    Each later normalised price becomes (1-weight)*intrinsic + weight*c_earlier
    at the same forward moneyness. A mix of two arbitrage-free slices is still
    arbitrage-free, so the only new violations are calendar ones: at every
    earlier quote with positive time value, of size (1-weight)*time value.
    The two expiries must share their K/F grid.
    """
    idx = [e.label for e in surface.expiries].index(later_label)
    if idx == 0:
        raise ValueError("the first expiry has no predecessor")
    if not 0 <= weight < 1:
        raise ValueError("weight must be in [0, 1)")
    earlier, later = surface.expiries[idx - 1], surface.expiries[idx]
    by_moneyness = {q.strike / earlier.forward: q for q in earlier.quotes}
    prices = {}
    for q in later.quotes:
        k = q.strike / later.forward
        if k not in by_moneyness:
            raise ValueError("expiries do not share a moneyness grid")
        c1 = by_moneyness[k].price / (earlier.discount * earlier.forward)
        intrinsic = lower_bound(later, q.strike) / (later.discount * later.forward)
        c2 = (1 - weight) * intrinsic + weight * c1
        prices[q.row] = c2 * later.discount * later.forward
    return surface.replace(_set_prices(later, prices))
