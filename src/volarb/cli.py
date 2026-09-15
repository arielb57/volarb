"""volarb command line: check a grid, or generate a synthetic one."""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from fractions import Fraction

from . import __version__
from .csvio import GridError, decimal, read_grid_file, write_grid
from .model import Surface
from .report import Report, analyze
from .synth import inject_bump, inject_calendar_crossing, inject_tilt, synthetic_surface

EXIT_CLEAN, EXIT_ARBITRAGE, EXIT_INPUT = 0, 1, 2


def _size(x: Fraction) -> str:
    return f"{float(x):.6g}"


def _table(rows: list[list[str]], header: list[str]) -> str:
    widths = [max(len(r[i]) for r in [header, *rows]) for i in range(len(header))]
    lines = ["  ".join(h.ljust(w) for h, w in zip(header, widths, strict=False)).rstrip()]
    lines.append("  ".join("-" * w for w in widths))
    lines += ["  ".join(c.ljust(w) for c, w in zip(r, widths, strict=False)).rstrip() for r in rows]
    return "\n".join(lines)


def _strike_of(surface: Surface, ref) -> str:
    for q in surface.expiry(ref.expiry).quotes:
        if q.row == ref.row:
            return decimal(q.strike, 6)
    return "?"


def render_text(surface: Surface, report: Report, limit: int) -> str:
    out = []
    n = report.quote_count
    out.append(f"{n} quotes in {len(surface.expiries)} expiries")
    if report.float_inputs:
        out.append(
            "note: prices were computed from implied vols with float Black-76 (math.erfc);"
            " that conversion is the only inexact step, and violations of size ~1e-12"
            " or below may be rounding in it"
        )
    if report.clean:
        out.append("no static arbitrage found")
        return "\n".join(out)

    counts = Counter(v.kind.value for v in report.violations)
    summary = ", ".join(f"{c} {k}" for k, c in sorted(counts.items()))
    out.append(f"{len(report.violations)} violations: {summary}")
    out.append("")
    ordered = sorted(report.violations, key=lambda v: (v.kind.value, v.expiry, -v.size))
    rows = []
    for v in ordered[:limit]:
        quotes = " ".join(f"{r.expiry}@K={_strike_of(surface, r)}" for r in v.quotes)
        rows.append([v.kind.value, v.expiry, quotes, _size(v.size)])
    out.append(_table(rows, ["kind", "expiry", "quotes", "size"]))
    if len(ordered) > limit:
        out.append(f"... {len(ordered) - limit} more (use --limit or --json)")

    out.append("")
    removed = report.removed
    out.append(f"minimum removal: {len(removed)} of {n} quotes")
    for rem in report.removals:
        if rem.removed:
            strikes = ", ".join(_strike_of(surface, r) for r in rem.removed)
            lines = ",".join(str(r.row) for r in rem.removed)
            out.append(f"  {rem.expiry}: K = {strikes}  (lines {lines})")
    if report.calendar_removed:
        out.append("  calendar (greedy, not proven minimal):")
        for r in report.calendar_removed:
            out.append(f"    {r.expiry}: K = {_strike_of(surface, r)}  (line {r.row})")
    out.append(f"violations after removal: {len(report.residual)}")
    return "\n".join(out)


def render_json(report: Report) -> str:
    def ref(r):
        return {"expiry": r.expiry, "row": r.row}

    doc = {
        "quotes": report.quote_count,
        "float_inputs": report.float_inputs,
        "violations": [
            {
                "kind": v.kind.value,
                "expiry": v.expiry,
                "quotes": [ref(r) for r in v.quotes],
                "size": str(v.size),
                "size_float": float(v.size),
                "detail": v.detail,
            }
            for v in report.violations
        ],
        "removal": {rem.expiry: [ref(r) for r in rem.removed] for rem in report.removals},
        "calendar_removal": [ref(r) for r in report.calendar_removed],
        "residual_violations": len(report.residual),
    }
    return json.dumps(doc, indent=2)


def cmd_check(args: argparse.Namespace) -> int:
    try:
        surface, from_iv = read_grid_file(args.grid)
    except (OSError, GridError) as exc:
        print(f"volarb: {exc}", file=sys.stderr)
        return EXIT_INPUT
    report = analyze(surface, float_inputs=from_iv)
    if args.json:
        print(render_json(report))
    else:
        print(render_text(surface, report, args.limit))
    return EXIT_CLEAN if report.clean else EXIT_ARBITRAGE


def cmd_generate(args: argparse.Namespace) -> int:
    rng = random.Random(args.seed)
    try:
        surface = synthetic_surface(
            rng,
            n_expiries=args.expiries,
            n_strikes=args.strikes,
            shared_moneyness=args.inject == "calendar",
        )
        labels = [e.label for e in surface.expiries]
        if args.inject == "bump":
            surface = inject_bump(surface, labels[0], args.strikes // 2)
        elif args.inject == "tilt":
            surface = inject_tilt(surface, labels[0], args.strikes - 3, Fraction(1, 100))
        elif args.inject == "calendar":
            surface = inject_calendar_crossing(surface, labels[-1])
    except (ValueError, IndexError) as exc:
        print(f"volarb: {exc}", file=sys.stderr)
        return EXIT_INPUT
    sys.stdout.write(write_grid(surface))
    return EXIT_CLEAN


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="volarb", description=__doc__)
    parser.add_argument("--version", action="version", version=f"volarb {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="check a CSV grid for static arbitrage")
    check.add_argument("grid", help="CSV with expiry,t,forward,discount,strike,price|iv")
    check.add_argument("--json", action="store_true", help="machine-readable output")
    check.add_argument("--limit", type=int, default=40, help="max violation rows to print")
    check.set_defaults(func=cmd_check)

    gen = sub.add_parser("generate", help="write a synthetic SVI grid as CSV to stdout")
    gen.add_argument("--seed", type=int, default=0)
    gen.add_argument("--expiries", type=int, default=3)
    gen.add_argument("--strikes", type=int, default=12)
    gen.add_argument("--inject", choices=["none", "bump", "tilt", "calendar"], default="none")
    gen.set_defaults(func=cmd_generate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
