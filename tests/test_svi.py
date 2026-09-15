import math
import random
from fractions import Fraction as F

import pytest

from volarb import Kind, check_expiry, check_surface
from volarb.black import black76_call, call_price_from_vol
from volarb.synth import VOGT, SviParams, random_strikes, random_svi, svi_expiry, synthetic_surface


def test_black76_matches_reference_value_and_parity():
    # F=100, K=100, T=1, vol=20%, DF=1: 100*(2N(0.1)-1) = 7.965567455405804
    assert math.isclose(black76_call(100, 100, 1, 0.2, 1), 7.965567455405804, rel_tol=1e-13)
    for k in (60.0, 90.0, 99.0, 101.0, 130.0):
        # Textbook form with erf; accurate near the money, where the two code paths meet.
        sd = 0.3 * math.sqrt(0.5)
        d1 = (math.log(100 / k) + sd * sd / 2) / sd
        n = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))  # noqa: E731
        textbook = 0.97 * (100 * n(d1) - k * n(d1 - sd))
        assert math.isclose(black76_call(100, k, 0.5, 0.3, 0.97), textbook, rel_tol=1e-12)


def test_black76_tails_keep_precision():
    far = black76_call(100, 400, 0.25, 0.2, 1)
    assert 0 <= far < 1e-30
    near_zero_vol = black76_call(100, 90, 1, 0.0, 0.9)
    assert near_zero_vol == pytest.approx(9.0)
    with pytest.raises(ValueError):
        black76_call(100, -1, 1, 0.2, 1)


def test_vol_conversion_clamps_float_rounding_to_exact_bounds():
    # float(22.31) is not 22.31, so the float intrinsic value lands just below the exact one.
    price = call_price_from_vol(F(100), F("22.31"), F(1), 0.19, F(1))
    assert price == F("77.69")
    assert call_price_from_vol(F(100), F(100), F(1), 50.0, F("0.9")) <= 90


def test_gj_condition_rejects_vogt_parameters():
    assert VOGT.min_g(-1.5, 1.5) < 0
    assert all(VOGT.total_variance(k / 10) > 0 for k in range(-15, 16))


def test_flat_smile_satisfies_gj():
    flat = SviParams(a=0.04, b=0.0, rho=0.0, m=0.0, sigma=0.1)
    assert flat.min_g(-2, 2) > 0.9


def test_vogt_slice_produces_butterfly_violations():
    strikes = [F(100) * F(math.exp(k / 20)).limit_denominator(1000) for k in range(-30, 31)]
    e = svi_expiry("V", F(1), F(100), F(1), VOGT, strikes)
    vs = check_expiry(e)
    kinds = {v.kind for v in vs}
    assert Kind.CONVEXITY in kinds and kinds <= {Kind.CONVEXITY, Kind.MONOTONICITY}
    # The arbitrage sits where g < 0, roughly k in (0.6, 1.3); nothing on the left wing.
    flagged = {r.row for v in vs for r in v.quotes}
    assert all(math.log(strikes[row] / 100) > 0.3 for row in flagged)


@pytest.mark.parametrize("seed", range(60))
def test_gj_compliant_svi_slices_on_random_grids_have_zero_violations(seed):
    rng = random.Random(seed)
    k_lo, k_hi = -0.4, 0.4
    params = random_svi(rng, k_lo, k_hi, margin=1e-3)
    assert params.min_g(k_lo, k_hi) >= 1e-3
    forward = F(100)
    strikes = random_strikes(rng, forward, rng.randint(2, 40), k_lo, k_hi)
    discount = F(rng.choice(["1", "0.99", "0.9"]))
    e = svi_expiry("S", F(1, 2), forward, discount, params, strikes)
    assert check_expiry(e) == []


@pytest.mark.parametrize("seed", range(20))
def test_calendar_consistent_svi_surfaces_are_clean(seed):
    rng = random.Random(1000 + seed)
    s = synthetic_surface(rng, n_expiries=4, n_strikes=20)
    assert check_surface(s) == []


def test_naive_parameters_can_break_gj_and_be_caught():
    rng = random.Random(3)
    caught = 0
    for _ in range(40):
        p = random_svi(rng, -1.0, 1.0, gj=False)
        if p.min_g(-1.0, 1.0) >= 0:
            continue
        strikes = random_strikes(rng, F(100), 60, -1.0, 1.0, tick=F(1, 100))
        if check_expiry(svi_expiry("N", F(1), F(100), F(1), p, strikes)):
            caught += 1
    assert caught > 0
