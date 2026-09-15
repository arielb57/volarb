"""volarb: exact static-arbitrage checks and minimum removal sets for option quote grids."""

from .checks import check_calendar, check_expiry, check_surface, is_arbitrage_free
from .model import Expiry, Kind, Quote, QuoteRef, Surface, Violation
from .repair import Removal, brute_force_min_removal, calendar_repair, min_removal
from .report import Report, analyze

__version__ = "0.1.0"

__all__ = [
    "Expiry",
    "Kind",
    "Quote",
    "QuoteRef",
    "Removal",
    "Report",
    "Surface",
    "Violation",
    "analyze",
    "brute_force_min_removal",
    "calendar_repair",
    "check_calendar",
    "check_expiry",
    "check_surface",
    "is_arbitrage_free",
    "min_removal",
]
