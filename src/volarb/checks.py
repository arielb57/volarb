"""Exact static-arbitrage checks on a quote grid."""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction
from itertools import groupby

from .csvio import decimal as d
from .model import Expiry, Kind, QuoteRef, Surface, Violation


@dataclass(frozen=True)
class Point:
    """A distinct (strike, price) pair; identical duplicate quotes collapse into one."""

    strike: Fraction
    price: Fraction
    refs: tuple[QuoteRef, ...]


def points(expiry: Expiry) -> list[Point]:
    out = []
    for (k, c), group in groupby(expiry.quotes, key=lambda q: (q.strike, q.price)):
        out.append(Point(k, c, tuple(expiry.ref(q) for q in group)))
    return out


def lower_bound(expiry: Expiry, strike: Fraction) -> Fraction:
    return max(expiry.discount * (expiry.forward - strike), Fraction(0))


def upper_bound(expiry: Expiry) -> Fraction:
    return expiry.discount * expiry.forward


def slope(a: Point, b: Point) -> Fraction:
    return (b.price - a.price) / (b.strike - a.strike)


def anchor_slope(expiry: Expiry, p: Point) -> Fraction:
    """Slope from the model-free point C(0) = DF·F to ``p``."""
    return (p.price - upper_bound(expiry)) / p.strike


def iter_expiry_violations(expiry: Expiry) -> Iterator[Violation]:
    """Yield violations for one expiry, cheapest checks first.

    Pair and triple checks run on consecutive distinct points with strictly
    increasing strike. When a strike carries conflicting prices those windows
    are skipped; the duplicate itself is reported instead.
    """
    label = expiry.label
    df = expiry.discount
    hi = upper_bound(expiry)
    pts = points(expiry)

    for p in pts:
        if p.price > hi:
            yield Violation(Kind.UPPER_BOUND, label, p.refs, p.price - hi, f"C > DF*F = {d(hi)}")
        lo = lower_bound(expiry, p.strike)
        if p.price < lo:
            yield Violation(
                Kind.LOWER_BOUND, label, p.refs, lo - p.price, f"C < max(DF*(F-K), 0) = {d(lo)}"
            )

    for strike, group in groupby(pts, key=lambda p: p.strike):
        group = list(group)
        if len(group) > 1:
            refs = tuple(r for p in group for r in p.refs)
            spread = group[-1].price - group[0].price
            yield Violation(
                Kind.DUPLICATE_STRIKE, label, refs, spread, f"{len(group)} prices at K={d(strike)}"
            )

    for a, b in zip(pts, pts[1:], strict=False):
        if a.strike == b.strike:
            continue
        s = slope(a, b)
        if s > 0:
            yield Violation(
                Kind.MONOTONICITY,
                label,
                a.refs + b.refs,
                b.price - a.price,
                f"price rises from K={d(a.strike)} to K={d(b.strike)}",
            )
        if s < -df:
            yield Violation(
                Kind.VERTICAL_SPREAD,
                label,
                a.refs + b.refs,
                (a.price - b.price) - df * (b.strike - a.strike),
                f"call spread {d(a.strike)}/{d(b.strike)} worth more than DF*width",
            )

    if len(pts) >= 2 and pts[0].strike < pts[1].strike:
        a, b = pts[0], pts[1]
        s0, s1 = anchor_slope(expiry, a), slope(a, b)
        if s0 > s1:
            yield Violation(
                Kind.CONVEXITY,
                label,
                a.refs + b.refs,
                2 * (s0 - s1) / b.strike,
                "butterfly with the K=0 point C=DF*F is negative",
            )

    for a, b, c in zip(pts, pts[1:], pts[2:], strict=False):
        if not a.strike < b.strike < c.strike:
            continue
        s_ab, s_bc = slope(a, b), slope(b, c)
        if s_ab > s_bc:
            yield Violation(
                Kind.CONVEXITY,
                label,
                a.refs + b.refs + c.refs,
                2 * (s_ab - s_bc) / (c.strike - a.strike),
                f"butterfly {d(a.strike)}/{d(b.strike)}/{d(c.strike)} is negative",
            )


def check_expiry(expiry: Expiry) -> list[Violation]:
    return list(iter_expiry_violations(expiry))


def is_arbitrage_free(expiry: Expiry) -> bool:
    return next(iter_expiry_violations(expiry), None) is None


def _normalised(expiry: Expiry, p: Point) -> tuple[Fraction, Fraction]:
    return p.strike / expiry.forward, p.price / (expiry.discount * expiry.forward)


def check_calendar(earlier: Expiry, later: Expiry) -> list[Violation]:
    """Calendar check between two expiries at equal forward moneyness K/F.

    Assumes zero dividends and forwards proportional across expiries, so the
    normalised price C/(DF·F) must not fall as maturity grows. Each earlier
    quote is compared with the later expiry's linear interpolant in strike.
    Because a chord lies on or above any convex curve through its endpoints,
    ``earlier > chord(later)`` is arbitrage against every arbitrage-free
    completion of the later slice. The reverse comparison would not be, so it
    is not made. Earlier quotes outside the later strike range are not checked.
    """
    if earlier.t >= later.t:
        raise ValueError("earlier expiry must have the smaller time")
    later_pts = []
    for _, group in groupby(points(later), key=lambda p: p.strike):
        # Conflicting duplicates: interpolate through the highest price so a
        # duplicate cannot manufacture a calendar violation on its own.
        later_pts.append(list(group)[-1])
    norm = [(_normalised(later, p), p) for p in later_pts]
    ks = [k for (k, _), _ in norm]
    label = f"{earlier.label}->{later.label}"
    out = []
    if not norm:
        return out
    for p in points(earlier):
        k1, c1 = _normalised(earlier, p)
        i = bisect_left(ks, k1)
        if i < len(ks) and ks[i] == k1:
            (_, c2), q = norm[i]
            brackets = q.refs
        elif 0 < i < len(ks):
            (klo, clo), plo = norm[i - 1]
            (khi, chi), phi = norm[i]
            c2 = clo + (chi - clo) * (k1 - klo) / (khi - klo)
            brackets = plo.refs + phi.refs
        else:
            continue
        if c1 > c2:
            out.append(
                Violation(
                    Kind.CALENDAR,
                    label,
                    p.refs + brackets,
                    c1 - c2,
                    f"C/(DF*F) at K/F={d(k1)} is higher for {earlier.label} than {later.label}",
                )
            )
    return out


def check_surface(surface: Surface) -> list[Violation]:
    out = []
    for e in surface.expiries:
        out.extend(iter_expiry_violations(e))
    for a, b in zip(surface.expiries, surface.expiries[1:], strict=False):
        out.extend(check_calendar(a, b))
    return out
