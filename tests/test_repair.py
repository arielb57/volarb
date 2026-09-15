import random
from fractions import Fraction as F

import pytest
from conftest import make_expiry, random_rough_expiry

from volarb import (
    QuoteRef,
    Surface,
    analyze,
    brute_force_min_removal,
    check_expiry,
    check_surface,
    is_arbitrage_free,
    min_removal,
)
from volarb.synth import inject_bump, inject_calendar_crossing, inject_tilt, synthetic_surface


def test_dp_matches_brute_force_on_2000_random_grids():
    rng = random.Random(20260915)
    nontrivial = 0
    for _ in range(2000):
        e = random_rough_expiry(rng, rng.randint(1, 12))
        dp = min_removal(e)
        brute = brute_force_min_removal(e)
        assert len(dp.removed) == len(brute.removed), e
        assert set(dp.removed) | set(dp.kept) == set(e.refs())
        assert not set(dp.removed) & set(dp.kept)
        assert is_arbitrage_free(e.without(dp.removed)), e
        nontrivial += bool(dp.removed)
    # The generator must actually exercise the repair, not just clean grids.
    assert nontrivial > 500


@pytest.mark.parametrize("seed", range(200))
def test_removing_reported_set_always_leaves_zero_violations(seed):
    rng = random.Random(seed)
    e = random_rough_expiry(rng, rng.randint(1, 40))
    removal = min_removal(e)
    assert check_expiry(e.without(removal.removed)) == []


def test_removal_set_is_empty_iff_grid_is_clean():
    rng = random.Random(5)
    for _ in range(300):
        e = random_rough_expiry(rng, rng.randint(1, 15))
        assert (min_removal(e).removed == ()) == is_arbitrage_free(e)


def test_single_bad_quote_among_good_ones():
    e = make_expiry([(80, 21), (90, 12), (100, 9), (110, 2), (120, "0.5")])
    assert min_removal(e).removed == (QuoteRef("E", 2),)


def test_out_of_bounds_quotes_are_always_removed():
    e = make_expiry([(80, 21), (90, 12), (100, 101), (110, 2), (120, -1)])
    assert set(min_removal(e).removed) == {QuoteRef("E", 2), QuoteRef("E", 4)}


def test_identical_duplicates_are_kept_together_and_count_twice():
    # Keeping both copies of (100, 9) beats keeping the single (100, 6)... but they conflict
    # with each other, so the DP must drop the lighter side.
    e = make_expiry([(90, 12), (100, 9), (100, 9), (100, 6), (110, 2)])
    removal = min_removal(e)
    assert len(removal.removed) == len(brute_force_min_removal(e).removed)
    assert check_expiry(e.without(removal.removed)) == []
    e2 = make_expiry([(90, 12), (100, 6), (100, 6), (100, "6.5"), (110, 2)])
    assert min_removal(e2).removed == (QuoteRef("E", 3),)


def test_empty_and_single_quote_expiries():
    empty = make_expiry([])
    assert min_removal(empty).removed == ()
    assert min_removal(make_expiry([(100, 7)])).removed == ()
    assert min_removal(make_expiry([(100, 700)])).removed == (QuoteRef("E", 0),)


def test_dp_scales_to_hundreds_of_strikes_and_stays_exact():
    rng = random.Random(11)
    e = random_rough_expiry(rng, 150)
    removal = min_removal(e)
    assert check_expiry(e.without(removal.removed)) == []


@pytest.mark.parametrize("seed", range(10))
def test_surface_report_residual_is_empty_after_all_injections(seed):
    rng = random.Random(seed)
    s = synthetic_surface(rng, n_expiries=3, n_strikes=12, shared_moneyness=True)
    labels = [e.label for e in s.expiries]
    s = inject_bump(s, labels[0], 4)
    s = inject_tilt(s, labels[1], 9, F(1, 500))
    s = inject_calendar_crossing(s, labels[2])
    report = analyze(s)
    assert report.violations
    kept = s.without(report.removed)
    assert check_surface(kept) == []
    assert report.residual == ()
    assert len(report.removed) == len(set(report.removed))


def test_surface_report_on_clean_surface():
    s = synthetic_surface(random.Random(1), n_expiries=2, n_strikes=10)
    report = analyze(s)
    assert report.clean and report.removed == () and report.residual == ()
    assert isinstance(s, Surface)
