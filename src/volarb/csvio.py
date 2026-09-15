"""CSV input and output for quote grids.

Columns: expiry, t, forward, discount, strike, and exactly one of price or iv.
Numbers are read as decimal strings straight into Fractions. Row ids are the
1-based line numbers of the file (the header is line 1).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from fractions import Fraction

from .black import call_price_from_vol
from .model import Expiry, Quote, Surface

REQUIRED = ("expiry", "t", "forward", "discount", "strike")


class GridError(ValueError):
    pass


def _number(text: str, column: str, line: int) -> Fraction:
    try:
        return Fraction(text.strip())
    except (ValueError, ZeroDivisionError):
        raise GridError(f"line {line}: {column} is not a number: {text!r}") from None


def read_grid(lines: Iterable[str]) -> tuple[Surface, bool]:
    """Parse a grid. Returns the surface and whether prices came from implied vols."""
    reader = csv.DictReader(lines)
    fields = [f.strip().lower() for f in (reader.fieldnames or [])]
    reader.fieldnames = fields
    missing = [c for c in REQUIRED if c not in fields]
    if missing:
        raise GridError(f"missing columns: {', '.join(missing)}")
    has_price, has_iv = "price" in fields, "iv" in fields
    if has_price == has_iv:
        raise GridError("provide exactly one of the columns 'price' or 'iv'")

    meta: dict[str, tuple[Fraction, Fraction, Fraction]] = {}
    quotes: dict[str, list[Quote]] = {}
    for line, row in enumerate(reader, start=2):
        if not any((v or "").strip() for v in row.values()):
            continue
        label = (row["expiry"] or "").strip()
        if not label:
            raise GridError(f"line {line}: empty expiry")
        t = _number(row["t"], "t", line)
        forward = _number(row["forward"], "forward", line)
        discount = _number(row["discount"], "discount", line)
        strike = _number(row["strike"], "strike", line)
        if meta.setdefault(label, (t, forward, discount)) != (t, forward, discount):
            raise GridError(f"line {line}: t/forward/discount differ within expiry {label}")
        if forward <= 0 or discount <= 0 or strike <= 0 or t < 0:
            raise GridError(f"line {line}: forward, discount and strike must be > 0, t >= 0")
        if has_price:
            price = _number(row["price"], "price", line)
        else:
            vol = _number(row["iv"], "iv", line)
            if vol < 0:
                raise GridError(f"line {line}: negative implied vol")
            price = call_price_from_vol(forward, strike, t, float(vol), discount)
        quotes.setdefault(label, []).append(Quote(strike, price, line))

    if not quotes:
        raise GridError("no quotes in grid")
    try:
        expiries = tuple(Expiry(label, *meta[label], tuple(qs)) for label, qs in quotes.items())
        return Surface(expiries), has_iv
    except ValueError as exc:
        raise GridError(str(exc)) from None


def read_grid_file(path: str) -> tuple[Surface, bool]:
    with open(path, newline="", encoding="utf-8") as fh:
        return read_grid(fh)


def decimal(x: Fraction, places: int = 10) -> str:
    """Fixed-point rendering, trailing zeros trimmed. Exact when x fits in ``places``."""
    scaled = round(x * 10**places)
    sign = "-" if scaled < 0 else ""
    whole, frac = divmod(abs(scaled), 10**places)
    frac_text = str(frac).rjust(places, "0").rstrip("0")
    return f"{sign}{whole}.{frac_text}" if frac_text else f"{sign}{whole}"


def write_grid(surface: Surface, places: int = 10) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["expiry", "t", "forward", "discount", "strike", "price"])
    for e in surface.expiries:
        for q in e.quotes:
            writer.writerow(
                [
                    e.label,
                    decimal(e.t, places),
                    decimal(e.forward, places),
                    decimal(e.discount, places),
                    decimal(q.strike, places),
                    decimal(q.price, places),
                ]
            )
    return out.getvalue()
