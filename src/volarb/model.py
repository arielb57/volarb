"""Quote grid data model. All numbers are exact Fractions."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction


@dataclass(frozen=True, order=True)
class QuoteRef:
    """Stable identity of one input quote: its expiry label and source row."""

    expiry: str
    row: int

    def __str__(self) -> str:
        return f"{self.expiry}#{self.row}"


@dataclass(frozen=True)
class Quote:
    strike: Fraction
    price: Fraction
    row: int


@dataclass(frozen=True)
class Expiry:
    label: str
    t: Fraction
    forward: Fraction
    discount: Fraction
    quotes: tuple[Quote, ...] = field(default=())

    def __post_init__(self) -> None:
        if self.t < 0:
            raise ValueError(f"expiry {self.label}: time must be >= 0")
        if self.forward <= 0:
            raise ValueError(f"expiry {self.label}: forward must be > 0")
        if not 0 < self.discount:
            raise ValueError(f"expiry {self.label}: discount factor must be > 0")
        rows = [q.row for q in self.quotes]
        if len(set(rows)) != len(rows):
            raise ValueError(f"expiry {self.label}: duplicate row ids")
        for q in self.quotes:
            if q.strike <= 0:
                raise ValueError(f"expiry {self.label} row {q.row}: strike must be > 0")
        ordered = tuple(sorted(self.quotes, key=lambda q: (q.strike, q.price, q.row)))
        object.__setattr__(self, "quotes", ordered)

    def ref(self, quote: Quote) -> QuoteRef:
        return QuoteRef(self.label, quote.row)

    def refs(self) -> list[QuoteRef]:
        return [self.ref(q) for q in self.quotes]

    def without(self, refs: Iterable[QuoteRef]) -> Expiry:
        drop = {r.row for r in refs if r.expiry == self.label}
        kept = tuple(q for q in self.quotes if q.row not in drop)
        return Expiry(self.label, self.t, self.forward, self.discount, kept)

    def with_quotes(self, quotes: Sequence[Quote]) -> Expiry:
        return Expiry(self.label, self.t, self.forward, self.discount, tuple(quotes))


@dataclass(frozen=True)
class Surface:
    expiries: tuple[Expiry, ...]

    def __post_init__(self) -> None:
        labels = [e.label for e in self.expiries]
        if len(set(labels)) != len(labels):
            raise ValueError("duplicate expiry labels")
        ordered = tuple(sorted(self.expiries, key=lambda e: e.t))
        for a, b in zip(ordered, ordered[1:], strict=False):
            if a.t == b.t:
                raise ValueError(f"expiries {a.label} and {b.label} have the same time")
        object.__setattr__(self, "expiries", ordered)

    def expiry(self, label: str) -> Expiry:
        for e in self.expiries:
            if e.label == label:
                return e
        raise KeyError(label)

    def without(self, refs: Iterable[QuoteRef]) -> Surface:
        refs = list(refs)
        return Surface(tuple(e.without(refs) for e in self.expiries))

    def replace(self, expiry: Expiry) -> Surface:
        return Surface(tuple(expiry if e.label == expiry.label else e for e in self.expiries))

    def quote_count(self) -> int:
        return sum(len(e.quotes) for e in self.expiries)


class Kind(str, Enum):
    UPPER_BOUND = "upper_bound"
    LOWER_BOUND = "lower_bound"
    DUPLICATE_STRIKE = "duplicate_strike"
    MONOTONICITY = "monotonicity"
    VERTICAL_SPREAD = "vertical_spread"
    CONVEXITY = "convexity"
    CALENDAR = "calendar"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Violation:
    """One static-arbitrage violation.

    ``size`` is always a positive Fraction; its unit depends on ``kind``:
    price for bounds, monotonicity, duplicates and vertical spreads; the
    negative second divided difference (per unit strike squared) for
    convexity; and a fraction of DF·F (normalised call price) for calendar.
    """

    kind: Kind
    expiry: str
    quotes: tuple[QuoteRef, ...]
    size: Fraction
    detail: str = ""
