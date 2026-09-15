from fractions import Fraction as F

import pytest
from conftest import make_expiry

from volarb import Kind, check_expiry, is_arbitrage_free
from volarb.model import Expiry, Quote, QuoteRef, Surface


def kinds(violations):
    return sorted(v.kind.value for v in violations)


def test_clean_convex_slice_has_no_violations():
    e = make_expiry([(80, 21), (90, 12), (100, 5), (110, 2), (120, "0.5")])
    assert check_expiry(e) == []
    assert is_arbitrage_free(e)


def test_upper_bound_violation_names_quote_and_exact_size():
    e = make_expiry([(50, "99.5")], forward=100, discount="0.99")
    (v,) = check_expiry(e)
    assert v.kind is Kind.UPPER_BOUND
    assert v.quotes == (QuoteRef("E", 0),)
    assert v.size == F("99.5") - F("99")


def test_lower_bound_uses_discounted_intrinsic():
    e = make_expiry([(80, "19.7")], forward=100, discount="0.99")
    (v,) = check_expiry(e)
    assert v.kind is Kind.LOWER_BOUND
    assert v.size == F("19.8") - F("19.7")


def test_lower_bound_is_exact_not_tolerant():
    at = make_expiry([(80, "19.8")], discount="0.99")
    below = make_expiry([(80, "19.7999999999999999999")], discount="0.99")
    assert check_expiry(at) == []
    assert kinds(check_expiry(below)) == ["lower_bound"]


def test_monotonicity_violation():
    e = make_expiry([(90, 10), (100, 11)])
    vs = check_expiry(e)
    assert kinds(vs) == ["monotonicity"]
    assert vs[0].quotes == (QuoteRef("E", 0), QuoteRef("E", 1))
    assert vs[0].size == 1


def test_vertical_spread_steeper_than_discount_factor():
    # Spread 90/100 worth 9.95 > DF*10 = 9.9; both prices within bounds.
    e = make_expiry([(90, "15"), (100, "5.05")], discount="0.99")
    vs = check_expiry(e)
    # Within bounds, the slope from C(0)=DF*F is always >= -DF, so a too-steep
    # spread is also a negative butterfly against the zero-strike point.
    assert kinds(vs) == ["convexity", "vertical_spread"]
    (vertical,) = (v for v in vs if v.kind is Kind.VERTICAL_SPREAD)
    assert vertical.size == F("9.95") - F("9.9")


def test_convexity_on_non_uniform_strikes_uses_divided_difference():
    # Chord from (90, 12) to (120, 2) at K=100 is 12 - 10/3 = 8.666..., price 9 is above it.
    e = make_expiry([(90, 12), (100, 9), (120, 2)])
    (v,) = check_expiry(e)
    assert v.kind is Kind.CONVEXITY
    s_ab, s_bc = F(-3, 10), F(-7, 20)
    assert v.size == 2 * (s_ab - s_bc) / 30
    # The same prices are convex once the right wing strike moves out to 130.
    assert check_expiry(make_expiry([(90, 12), (100, 9), (130, 2)])) == []


def test_collinear_butterfly_is_allowed():
    assert check_expiry(make_expiry([(90, 12), (100, 8), (110, 4)])) == []


def test_convexity_with_model_free_zero_strike_point():
    # C(0) = DF*F = 100. Slope 0 -> 50 is -1/50, slope 50 -> 60 is -1/2: concave.
    e = make_expiry([(50, 99), (60, 94)])
    (v,) = check_expiry(e)
    assert v.kind is Kind.CONVEXITY
    assert v.quotes == (QuoteRef("E", 0), QuoteRef("E", 1))
    assert v.size == 2 * (F(-1, 50) - F(-1, 2)) / 60


def test_single_quote_only_checks_bounds():
    assert check_expiry(make_expiry([(100, 7)])) == []
    assert kinds(check_expiry(make_expiry([(100, 101)]))) == ["upper_bound"]


def test_empty_expiry_is_clean():
    assert check_expiry(Expiry("E", F(1), F(100), F(1), ())) == []


def test_zero_price_deep_otm_wings_are_valid():
    e = make_expiry([(90, 10), (100, 3), (150, 0), (200, 0), (300, 0)])
    assert check_expiry(e) == []


def test_zero_then_positive_wing_is_monotonicity_arbitrage():
    e = make_expiry([(90, 10), (100, 3), (150, 0), (200, "0.01")])
    vs = check_expiry(e)
    assert kinds(vs) == ["monotonicity"]
    assert vs[0].quotes == (QuoteRef("E", 2), QuoteRef("E", 3))


def test_strike_exactly_at_forward():
    at_intrinsic = make_expiry([(100, 0)], forward=100)
    assert check_expiry(at_intrinsic) == []
    e = make_expiry([(90, "10"), (100, 0), (110, 0)], forward=100)
    assert check_expiry(e) == []
    e = make_expiry([(90, "10.5"), (100, "6"), (110, "0.5")], forward=100)
    assert kinds(check_expiry(e)) == ["convexity"]


def test_identical_duplicate_strikes_are_one_point():
    e = make_expiry([(90, 12), (100, 6), (100, 6), (110, 2)])
    assert check_expiry(e) == []


def test_conflicting_duplicate_strikes_reported_with_spread():
    e = make_expiry([(90, 12), (100, 6), (100, "6.5"), (110, 2)])
    vs = check_expiry(e)
    dup = [v for v in vs if v.kind is Kind.DUPLICATE_STRIKE]
    assert len(dup) == 1
    assert set(dup[0].quotes) == {QuoteRef("E", 1), QuoteRef("E", 2)}
    assert dup[0].size == F("0.5")


def test_expiry_validation():
    with pytest.raises(ValueError):
        make_expiry([(0, 1)])
    with pytest.raises(ValueError):
        Expiry("E", F(1), F(0), F(1), ())
    with pytest.raises(ValueError):
        Expiry("E", F(1), F(100), F(1), (Quote(F(90), F(1), 0), Quote(F(95), F(1), 0)))
    with pytest.raises(ValueError):
        Surface((make_expiry([], label="A", t=1), make_expiry([], label="B", t=1)))
