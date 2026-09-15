import random
from fractions import Fraction as F

import pytest

from volarb import Kind, QuoteRef, analyze, check_surface, min_removal
from volarb.synth import inject_bump, inject_calendar_crossing, inject_tilt, synthetic_surface


def clean_surface(seed, n_expiries=1, n_strikes=14, shared=False):
    rng = random.Random(seed)
    s = synthetic_surface(rng, n_expiries=n_expiries, n_strikes=n_strikes, shared_moneyness=shared)
    assert check_surface(s) == []
    return s


@pytest.mark.parametrize("seed", range(25))
def test_bump_creates_exactly_one_convexity_violation_at_the_bumped_quote(seed):
    s = clean_surface(seed)
    e = s.expiries[0]
    index = random.Random(seed).randrange(1, len(e.quotes) - 1)
    bumped = inject_bump(s, e.label, index)
    q = [e.quotes[index - 1], e.quotes[index], e.quotes[index + 1]]
    (v,) = check_surface(bumped)
    assert v.kind is Kind.CONVEXITY
    assert v.quotes == tuple(QuoteRef(e.label, x.row) for x in q)
    # One quote always suffices; dropping a neighbour can tie with the bumped one.
    removal = min_removal(bumped.expiries[0])
    assert len(removal.removed) == 1 and removal.removed[0] in v.quotes


@pytest.mark.parametrize("seed", range(25))
def test_tilt_creates_monotonicity_violations_on_every_tilted_pair_only(seed):
    s = clean_surface(seed)
    e = s.expiries[0]
    n = len(e.quotes)
    start = random.Random(seed).randrange(n // 2, n - 1)
    tilted = inject_tilt(s, e.label, start, F(1, 1000))
    vs = check_surface(tilted)
    assert {v.kind for v in vs} == {Kind.MONOTONICITY}
    expected = {
        (QuoteRef(e.label, a.row), QuoteRef(e.label, b.row))
        for a, b in zip(e.quotes[start:], e.quotes[start + 1 :], strict=False)
    }
    assert {v.quotes for v in vs} == expected
    first = min(vs, key=lambda v: v.quotes)
    assert first.quotes[0].row == e.quotes[start].row


@pytest.mark.parametrize("seed", range(15))
def test_calendar_crossing_creates_calendar_violations_only_where_time_value_exists(seed):
    s = clean_surface(seed, n_expiries=3, n_strikes=12, shared=True)
    earlier, later = s.expiries[1], s.expiries[2]
    weight = F(1, 3)
    crossed = inject_calendar_crossing(s, later.label, weight)
    vs = check_surface(crossed)
    assert vs and {v.kind for v in vs} == {Kind.CALENDAR}
    assert {v.expiry for v in vs} == {f"{earlier.label}->{later.label}"}
    expected_rows = set()
    for q in earlier.quotes:
        norm = earlier.discount * earlier.forward
        time_value = (q.price - max(earlier.discount * (earlier.forward - q.strike), 0)) / norm
        if time_value > 0:
            expected_rows.add(q.row)
            (v,) = (v for v in vs if v.quotes[0].row == q.row)
            assert v.size == (1 - weight) * time_value
            assert v.quotes[1].expiry == later.label
    assert {v.quotes[0].row for v in vs} == expected_rows

    report = analyze(crossed)
    assert all(not r.removed for r in report.removals)
    assert set(report.calendar_removed) == {QuoteRef(earlier.label, r) for r in expected_rows}
    assert report.residual == ()


def test_injection_argument_validation():
    s = clean_surface(0, n_expiries=2, n_strikes=8)
    label = s.expiries[0].label
    with pytest.raises(ValueError):
        inject_bump(s, label, 0)
    with pytest.raises(ValueError):
        inject_bump(s, label, 3, F(1))
    with pytest.raises(ValueError):
        inject_tilt(s, label, 7, F(1, 100))
    with pytest.raises(ValueError):
        inject_tilt(s, label, 0, F(1000))
    with pytest.raises(ValueError):
        inject_calendar_crossing(s, label)
    with pytest.raises(ValueError):
        inject_calendar_crossing(s, s.expiries[1].label)
