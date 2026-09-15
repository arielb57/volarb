"""Black-76 call prices from implied vols. The only floating-point step in volarb."""

from __future__ import annotations

import math
from fractions import Fraction


def norm_cdf(x: float) -> float:
    # erfc keeps relative precision in the tails; 0.5*(1+erf(x)) rounds to 0 below x ~ -8.
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def black76_call(forward: float, strike: float, t: float, vol: float, discount: float) -> float:
    """Discounted Black-76 call price.

    In-the-money calls are priced through put-call parity so both legs are
    computed from small tail probabilities rather than differences near one.
    """
    if forward <= 0 or strike <= 0 or discount <= 0:
        raise ValueError("forward, strike and discount must be positive")
    if vol < 0 or t < 0:
        raise ValueError("vol and time must be non-negative")
    intrinsic = max(forward - strike, 0.0)
    sd = vol * math.sqrt(t)
    if sd == 0.0:
        return discount * intrinsic
    d1 = (math.log(forward / strike) + 0.5 * sd * sd) / sd
    d2 = d1 - sd
    if strike >= forward:
        undiscounted = forward * norm_cdf(d1) - strike * norm_cdf(d2)
    else:
        put = strike * norm_cdf(-d2) - forward * norm_cdf(-d1)
        undiscounted = max(put, 0.0) + (forward - strike)
    return discount * min(max(undiscounted, intrinsic), forward)


def call_price_from_vol(
    forward: Fraction, strike: Fraction, t: Fraction, vol: float, discount: Fraction
) -> Fraction:
    """Black-76 price as an exact Fraction, clamped to the exact static bounds.

    The true Black price always lies in [max(DF(F-K), 0), DF·F]; only float
    rounding (including float(strike) itself) can push it outside, so the clamp
    removes rounding without hiding any arbitrage in the vols.
    """
    raw = Fraction(black76_call(float(forward), float(strike), float(t), vol, float(discount)))
    lower = max(discount * (forward - strike), Fraction(0))
    return min(max(raw, lower), discount * forward)
