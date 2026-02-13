from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from app.models import TermRange

MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024

TERM_RANGES: tuple[TermRange, ...] = (
    TermRange("Jan-Feb", 1, 2),
    TermRange("Mar-Apr", 3, 4),
    TermRange("Mai-Jun", 5, 6),
    TermRange("Jul-Aug", 7, 8),
    TermRange("Sep-Okt", 9, 10),
    TermRange("Nov-Des", 11, 12),
)


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def sanitize_filename(filename: str) -> str:
    normalized = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.strip().replace(" ", "_")
    normalized = re.sub(r"[^A-Za-z0-9._-]", "", normalized)
    if not normalized:
        return "attachment"
    return normalized[:120]


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return float(value)
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_date(value: str) -> str:
    datetime.strptime(value, "%Y-%m-%d")
    return value


def calculate_nok_amount(amount_original: float, currency: str, amount_nok: float | None, exchange_rate: float | None) -> float | None:
    if amount_nok is not None:
        return round(amount_nok, 2)
    if exchange_rate is not None:
        return round(amount_original * exchange_rate, 2)
    if currency == "NOK":
        return round(amount_original, 2)
    return None


def to_month_range(term_index: int) -> TermRange:
    if term_index < 1 or term_index > len(TERM_RANGES):
        raise ValueError("Ugyldig termin")
    return TERM_RANGES[term_index - 1]
