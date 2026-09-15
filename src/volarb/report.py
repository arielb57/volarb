"""Surface-wide report: every violation, and a removal set that clears them."""

from __future__ import annotations

from dataclasses import dataclass

from .checks import check_surface
from .model import QuoteRef, Surface, Violation
from .repair import Removal, calendar_repair, min_removal


@dataclass(frozen=True)
class Report:
    violations: tuple[Violation, ...]
    removals: tuple[Removal, ...]
    """Per-expiry minimum removal sets (provably smallest for each expiry alone)."""
    calendar_removed: tuple[QuoteRef, ...]
    """Extra quotes dropped greedily to clear calendar violations (not proven minimal)."""
    residual: tuple[Violation, ...]
    """Violations left after removing everything above. Empty unless there is a bug."""
    quote_count: int
    float_inputs: bool = False

    @property
    def removed(self) -> tuple[QuoteRef, ...]:
        return tuple(r for rem in self.removals for r in rem.removed) + self.calendar_removed

    @property
    def clean(self) -> bool:
        return not self.violations


def analyze(surface: Surface, *, float_inputs: bool = False) -> Report:
    violations = check_surface(surface)
    removals = tuple(min_removal(e) for e in surface.expiries)
    repaired = surface.without(r for rem in removals for r in rem.removed)
    calendar_removed = calendar_repair(repaired)
    repaired = repaired.without(calendar_removed)
    residual = check_surface(repaired)
    return Report(
        violations=tuple(violations),
        removals=removals,
        calendar_removed=calendar_removed,
        residual=tuple(residual),
        quote_count=surface.quote_count(),
        float_inputs=float_inputs,
    )
