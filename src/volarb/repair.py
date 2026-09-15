"""Minimum removal sets: the fewest quotes to drop to make a grid arbitrage-free."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations

from .checks import anchor_slope, check_calendar, is_arbitrage_free, lower_bound, points, slope
from .checks import upper_bound as price_cap
from .model import Expiry, QuoteRef, Surface


@dataclass(frozen=True)
class Removal:
    expiry: str
    removed: tuple[QuoteRef, ...]
    kept: tuple[QuoteRef, ...]


class _Incoming:
    """All feasible edges arriving at one node, sorted by slope, with prefix maxima.

    ``best(t)`` answers: among edges into this node whose slope is <= t, which
    path reaching it keeps the most quotes? That is exactly the convexity
    constraint for extending the path with an outgoing edge of slope t.
    """

    __slots__ = ("slopes", "best_value", "best_edge")

    def __init__(self, edges: list[tuple[Fraction, int, int]]) -> None:
        edges.sort(key=lambda e: e[0])
        self.slopes = [e[0] for e in edges]
        self.best_value: list[int] = []
        self.best_edge: list[int] = []
        value, edge = -1, -1
        for _, v, eid in edges:
            if v > value:
                value, edge = v, eid
            self.best_value.append(value)
            self.best_edge.append(edge)

    def best(self, t: Fraction) -> tuple[int, int]:
        i = bisect_right(self.slopes, t) - 1
        if i < 0:
            return -1, -1
        return self.best_value[i], self.best_edge[i]


def min_removal(expiry: Expiry) -> Removal:
    """Smallest set of quotes whose removal leaves ``expiry`` arbitrage-free.

    Distinct (strike, price) points are nodes of a DAG ordered by strike, with
    a fixed source at the model-free point C(0) = DF·F. An edge i -> j is
    allowed when both points meet the price bounds and the slope lies in
    [-DF, 0]. Consecutive edges must have non-decreasing slope (convexity).
    The kept set is the heaviest such path, weight = quotes per point.

    The textbook recurrence over (previous, current) pairs is O(n^3). Keeping
    each node's incoming edges sorted by slope with prefix maxima turns the
    inner max into a binary search, giving O(n^2 log n) exact comparisons.
    """
    df = expiry.discount
    cap = price_cap(expiry)
    nodes = [p for p in points(expiry) if lower_bound(expiry, p.strike) <= p.price <= cap]

    # edge record: (from_node or -1 for the anchor, to_node, value, parent_edge)
    edges: list[tuple[int, int, int, int]] = []
    incoming: list[_Incoming] = []
    best_value, best_edge = 0, -1

    for j, pj in enumerate(nodes):
        weight = len(pj.refs)
        arriving: list[tuple[Fraction, int, int]] = []

        edges.append((-1, j, weight, -1))
        arriving.append((anchor_slope(expiry, pj), weight, len(edges) - 1))

        for i in range(j):
            pi = nodes[i]
            if pi.strike == pj.strike:
                continue
            s = slope(pi, pj)
            if s > 0 or s < -df:
                continue
            value, parent = incoming[i].best(s)
            if parent < 0:
                continue
            edges.append((i, j, value + weight, parent))
            arriving.append((s, value + weight, len(edges) - 1))

        for _, v, eid in arriving:
            if v > best_value:
                best_value, best_edge = v, eid
        incoming.append(_Incoming(arriving))

    kept_rows: set[int] = set()
    eid = best_edge
    while eid >= 0:
        _, to_node, _, parent = edges[eid]
        kept_rows.update(r.row for r in nodes[to_node].refs)
        eid = parent

    all_refs = expiry.refs()
    kept = tuple(r for r in all_refs if r.row in kept_rows)
    removed = tuple(r for r in all_refs if r.row not in kept_rows)
    return Removal(expiry.label, removed, kept)


def brute_force_min_removal(expiry: Expiry) -> Removal:
    """Reference implementation: try every subset, largest first. Exponential."""
    quotes = expiry.quotes
    n = len(quotes)
    for size in range(n, -1, -1):
        for keep in combinations(range(n), size):
            candidate = expiry.with_quotes([quotes[i] for i in keep])
            if is_arbitrage_free(candidate):
                keep_set = set(keep)
                kept = tuple(expiry.ref(quotes[i]) for i in keep)
                removed = tuple(expiry.ref(q) for i, q in enumerate(quotes) if i not in keep_set)
                return Removal(expiry.label, removed, kept)
    raise AssertionError("the empty subset is always arbitrage-free")


def calendar_repair(surface: Surface) -> tuple[QuoteRef, ...]:
    """Greedily drop earlier-expiry quotes until no calendar violation remains.

    Expects every expiry to be arbitrage-free on its own. Dropping a quote
    keeps a slice arbitrage-free and can only raise the chords that later
    comparisons use, so each removal never creates a new violation and the
    loop ends. The result is not guaranteed to be the smallest such set.
    """
    removed: list[QuoteRef] = []
    current = surface
    while True:
        worst = None
        for a, b in zip(current.expiries, current.expiries[1:], strict=False):
            for v in check_calendar(a, b):
                if worst is None or v.size > worst[0].size:
                    worst = (v, a.label)
        if worst is None:
            return tuple(removed)
        violation, earlier = worst
        drop = [r for r in violation.quotes if r.expiry == earlier]
        removed.extend(drop)
        current = current.without(drop)
