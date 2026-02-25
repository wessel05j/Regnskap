from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app import db
from app.utils import TERM_RANGES, to_month_range


@dataclass(frozen=True, slots=True)
class VatCodeRule:
    mva_code: str
    label: str
    computed: bool


VAT_CODE_RULES: dict[str, VatCodeRule] = {
    "3": VatCodeRule("3", "Utgaende MVA hoy sats", True),
    "31": VatCodeRule("31", "Utgaende MVA middels sats", True),
    "32": VatCodeRule("32", "Utgaende MVA lav sats", True),
    "81": VatCodeRule("81", "Inngaende MVA hoy sats", False),
    "82": VatCodeRule("82", "Inngaende MVA middels sats", False),
    "83": VatCodeRule("83", "Inngaende MVA lav sats", False),
}


def to_decimal_rate(raw_rate: float | int | None) -> float | None:
    if raw_rate is None:
        return None
    rate = float(raw_rate)
    if rate > 1.0:
        rate = rate / 100.0
    return rate


def validate_vat_line_fields(
    *,
    vat_mva_code: str | None,
    vat_rate: float | None,
    vat_base_nok: int | None,
    vat_amount_nok: int | None,
) -> list[str]:
    errors: list[str] = []
    if not vat_mva_code:
        if vat_base_nok is not None or vat_amount_nok is not None or vat_rate is not None:
            errors.append("VAT-felt kan ikke settes uten mvaKode.")
        return errors

    rule = VAT_CODE_RULES.get(vat_mva_code)
    if rule is None:
        errors.append(f"Ukjent mvaKode: {vat_mva_code}")
        return errors

    if vat_base_nok is None:
        errors.append("vat_base_nok mangler for mva-linje.")
    if vat_amount_nok is None:
        errors.append("vat_amount_nok mangler for mva-linje.")

    if vat_base_nok is not None and not isinstance(vat_base_nok, int):
        errors.append("vat_base_nok ma vaere heltall i NOK.")
    if vat_amount_nok is not None and not isinstance(vat_amount_nok, int):
        errors.append("vat_amount_nok ma vaere heltall i NOK.")

    normalized_rate = to_decimal_rate(vat_rate)
    if rule.computed:
        if normalized_rate is None:
            errors.append(f"mvaKode {vat_mva_code} krever sats for beregnet MVA.")
        elif vat_base_nok is not None and vat_amount_nok is not None:
            expected = math.floor(vat_base_nok * normalized_rate)
            acceptable = {expected}
            # Reversal lines should be able to cancel original VAT exactly in whole NOK.
            if vat_base_nok < 0:
                acceptable.add(-math.floor(abs(vat_base_nok) * normalized_rate))
            if vat_amount_nok not in acceptable:
                errors.append(
                    f"mvaKode {vat_mva_code}: vat_amount_nok={vat_amount_nok}, forventet floor({vat_base_nok} * {normalized_rate:.6f})={expected}"
                )
    return errors


def term_date_range(year: int, term_index: int) -> tuple[str, str, str]:
    term = to_month_range(term_index)
    start_date = f"{year}-{term.month_start:02d}-01"
    if term.month_end in (2,):
        end_date = f"{year}-02-29" if _is_leap_year(year) else f"{year}-02-28"
    elif term.month_end in (4, 6, 9, 11):
        end_date = f"{year}-{term.month_end:02d}-30"
    else:
        end_date = f"{year}-{term.month_end:02d}-31"
    return term.label, start_date, end_date


def _is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def validate_vat_lines_for_term(year: int, term_index: int) -> list[dict[str, Any]]:
    _, start_date, end_date = term_date_range(year, term_index)
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                vl.id AS voucher_line_id,
                v.id AS voucher_id,
                v.voucher_no,
                v.voucher_series,
                vl.vat_mva_code,
                vl.vat_rate,
                vl.vat_base_nok,
                vl.vat_amount_nok
            FROM voucher_lines vl
            JOIN vouchers v ON v.id = vl.voucher_id
            WHERE v.posting_date BETWEEN ? AND ?
              AND vl.vat_mva_code IS NOT NULL
            ORDER BY v.posting_date, v.voucher_no, vl.line_no
            """,
            (start_date, end_date),
        ).fetchall()
    finally:
        conn.close()

    errors: list[dict[str, Any]] = []
    for row in rows:
        row_errors = validate_vat_line_fields(
            vat_mva_code=row["vat_mva_code"],
            vat_rate=row["vat_rate"],
            vat_base_nok=row["vat_base_nok"],
            vat_amount_nok=row["vat_amount_nok"],
        )
        for message in row_errors:
            errors.append(
                {
                    "voucher_id": row["voucher_id"],
                    "voucher_line_id": row["voucher_line_id"],
                    "voucher_ref": f"{row['voucher_series']}-{row['voucher_no']}",
                    "message": message,
                }
            )
    return errors


def aggregate_vat_term(year: int, term_index: int) -> dict[str, Any]:
    term_label, start_date, end_date = term_date_range(year, term_index)
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                vl.id AS voucher_line_id,
                vl.line_no AS voucher_line_no,
                vl.vat_mva_code,
                vl.vat_rate,
                vl.vat_base_nok,
                vl.vat_amount_nok,
                vl.description AS line_description,
                vl.bilag_id AS line_bilag_id,
                v.id AS voucher_id,
                v.voucher_series,
                v.voucher_no,
                v.voucher_type,
                v.posting_date,
                v.document_date,
                v.counterparty_name,
                v.description AS voucher_description,
                v.bilag_id AS voucher_bilag_id,
                bf.id AS bilag_id,
                bf.original_name AS bilag_original_name,
                bf.stored_name AS bilag_stored_name
            FROM voucher_lines vl
            JOIN vouchers v ON v.id = vl.voucher_id
            LEFT JOIN bilag_files bf ON bf.id = COALESCE(vl.bilag_id, v.bilag_id)
            WHERE v.posting_date BETWEEN ? AND ?
              AND vl.vat_mva_code IS NOT NULL
            ORDER BY vl.vat_mva_code, vl.vat_rate, v.posting_date, v.voucher_no, vl.line_no
            """,
            (start_date, end_date),
        ).fetchall()
    finally:
        conn.close()

    grouped: dict[tuple[str, float | None], dict[str, Any]] = {}
    for row in rows:
        rate = to_decimal_rate(row["vat_rate"])
        key = (str(row["vat_mva_code"]), rate)
        if key not in grouped:
            grouped[key] = {
                "mvaKode": str(row["vat_mva_code"]),
                "grunnlag_nok": 0,
                "sats": rate,
                "merverdiavgift_nok": 0,
                "drilldown": [],
            }
        base = int(row["vat_base_nok"] or 0)
        amount = int(row["vat_amount_nok"] or 0)
        grouped[key]["grunnlag_nok"] += base
        grouped[key]["merverdiavgift_nok"] += amount
        grouped[key]["drilldown"].append(
            {
                "voucher_id": row["voucher_id"],
                "voucher_line_id": row["voucher_line_id"],
                "voucher_line_no": row["voucher_line_no"],
                "voucher_ref": f"{row['voucher_series']}-{row['voucher_no']}",
                "voucher_type": row["voucher_type"],
                "posting_date": row["posting_date"],
                "document_date": row["document_date"],
                "counterparty_name": row["counterparty_name"],
                "line_description": row["line_description"],
                "voucher_description": row["voucher_description"],
                "grunnlag_nok": base,
                "merverdiavgift_nok": amount,
                "bilag": (
                    {
                        "id": row["bilag_id"],
                        "original_name": row["bilag_original_name"],
                        "stored_name": row["bilag_stored_name"],
                    }
                    if row["bilag_id"] is not None
                    else None
                ),
            }
        )

    lines = sorted(grouped.values(), key=lambda item: (item["mvaKode"], item["sats"] or -1))
    totals = {
        "grunnlag_nok": int(sum(line["grunnlag_nok"] for line in lines)),
        "merverdiavgift_nok": int(sum(line["merverdiavgift_nok"] for line in lines)),
    }
    validations = validate_vat_lines_for_term(year, term_index)

    return {
        "year": year,
        "term_index": term_index,
        "term_label": term_label,
        "start_date": start_date,
        "end_date": end_date,
        "line_count": len(lines),
        "lines": lines,
        "totals": totals,
        "validation_errors": validations,
    }


def export_vat_term_dataset_json(
    year: int,
    term_index: int,
    output_dir: Path,
    *,
    filename_prefix: str = "vat_term_dataset",
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset = aggregate_vat_term(year, term_index)
    output_path = output_dir / f"{filename_prefix}_{year}_t{term_index}.json"
    output_path.write_text(json.dumps(dataset, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path


def term_choices() -> list[tuple[int, str]]:
    return [(idx + 1, term.label) for idx, term in enumerate(TERM_RANGES)]
