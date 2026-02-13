from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class DashboardSummary:
    income_total_nok: float
    expense_total_nok: float
    result_nok: float
    missing_nok_count: int


@dataclass(slots=True)
class TermRange:
    label: str
    month_start: int
    month_end: int

