from fractions import Fraction as F

import pytest
from conftest import make_expiry

from volarb import Kind, QuoteRef, Surface, check_calendar, check_surface


def test_later_expiry_cheaper_at_same_strike_is_calendar_arbitrage():
    early = make_expiry([(90, 12), (100, 5), (110, 2)], label="A", t=F(1, 4))
    late = make_expiry([(90, 13), (100, "4.5"), (110, 3)], label="B", t=F(1, 2))
    (v,) = check_calendar(early, late)
    assert v.kind is Kind.CALENDAR
    assert v.quotes == (QuoteRef("A", 1), QuoteRef("B", 1))
    assert v.size == F("0.5") / 100


def test_mismatched_grids_interpolate_later_expiry_linearly():
    early = make_expiry([(90, 12), (100, 7), (110, 2)], label="A", t=F(1, 4))
    late = make_expiry([(95, 10), (105, 3)], label="B", t=F(1, 2))
    vs = check_calendar(early, late)
    # 90 and 110 are outside the later strike range; only K=100 is compared,
    # against (10 + 3) / 2 = 6.5 < 7.
    assert len(vs) == 1
    assert vs[0].quotes == (QuoteRef("A", 1), QuoteRef("B", 0), QuoteRef("B", 1))
    assert vs[0].size == F("0.5") / 100


def test_interpolation_at_non_midpoint():
    early = make_expiry([(100, "6.1")], label="A", t=F(1, 4))
    late = make_expiry([(95, 10), (115, 2)], label="B", t=F(1, 2))
    # interpolant at 100: 10 - 8 * 5/20 = 8
    assert check_calendar(early, late) == []
    early = make_expiry([(100, "8.01")], label="A", t=F(1, 4))
    (v,) = check_calendar(early, late)
    assert v.size == F("0.01") / 100


def test_calendar_compares_forward_moneyness_and_normalised_price():
    # Later forward is 110, discount 0.9: K=110 there is K/F = 1, like K=100 early.
    early = make_expiry([(100, 8)], label="A", t=F(1, 4), forward=100, discount=1)
    later_ok = make_expiry([(110, "7.92")], label="B", t=F(1, 2), forward=110, discount="0.9")
    assert check_calendar(early, later_ok) == []
    later_bad = make_expiry([(110, "7.91")], label="B", t=F(1, 2), forward=110, discount="0.9")
    (v,) = check_calendar(early, later_bad)
    assert v.size == F(8, 100) - F("7.91") / 99


def test_later_quote_below_earlier_chord_is_not_flagged():
    # A later price under the earlier chord does not prove arbitrage: only
    # earlier quotes are compared against the later interpolant.
    early = make_expiry([(90, 12), (110, 2)], label="A", t=F(1, 4))
    late = make_expiry([(90, 12), (100, "6.5"), (110, 2)], label="B", t=F(1, 2))
    assert check_calendar(early, late) == []


def test_order_is_enforced_and_surface_sorts_by_time():
    a = make_expiry([(100, 5)], label="A", t=F(1, 4))
    b = make_expiry([(100, 4)], label="B", t=F(1, 2))
    with pytest.raises(ValueError):
        check_calendar(b, a)
    s = Surface((b, a))
    assert [e.label for e in s.expiries] == ["A", "B"]
    assert [v.kind for v in check_surface(s)] == [Kind.CALENDAR]


def test_empty_later_expiry_yields_nothing():
    a = make_expiry([(100, 5)], label="A", t=F(1, 4))
    b = make_expiry([], label="B", t=F(1, 2))
    assert check_calendar(a, b) == []
