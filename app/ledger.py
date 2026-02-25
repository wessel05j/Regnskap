from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app import db, vat_engine


class LedgerError(ValueError):
    pass


@dataclass(slots=True)
class VoucherLineInput:
    account_no: str
    debit_nok: int
    credit_nok: int
    description: str = ""
    vat_mva_code: str | None = None
    vat_rate: float | None = None
    vat_base_nok: int | None = None
    vat_amount_nok: int | None = None
    bilag_id: int | None = None
    legacy_row_type: str | None = None
    legacy_row_id: int | None = None


def _parse_date(value: str, field_name: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise LedgerError(f"Ugyldig dato i {field_name}: {value}") from exc
    return value


def _to_int(value: Any, field_name: str) -> int:
    if value is None:
        raise LedgerError(f"{field_name} mangler")
    if isinstance(value, bool):
        raise LedgerError(f"{field_name} kan ikke vaere bool")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            raise LedgerError(f"{field_name} ma vaere heltall i NOK")
        return int(value)
    text = str(value).strip()
    if not text:
        raise LedgerError(f"{field_name} mangler")
    try:
        parsed = int(text)
    except ValueError as exc:
        raise LedgerError(f"{field_name} ma vaere heltall i NOK") from exc
    return parsed


def _audit_log(
    conn: sqlite3.Connection,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str | int | None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO audit_log (actor, action, entity_type, entity_id, before_json, after_json, reason)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            actor,
            action,
            entity_type,
            str(entity_id) if entity_id is not None else None,
            json.dumps(before, ensure_ascii=False) if before is not None else None,
            json.dumps(after, ensure_ascii=False) if after is not None else None,
            reason,
        ),
    )


def list_accounts(active_only: bool = True) -> list[dict[str, Any]]:
    conn = db.get_connection()
    try:
        if active_only:
            rows = conn.execute("SELECT * FROM accounts WHERE active = 1 ORDER BY account_no").fetchall()
        else:
            rows = conn.execute("SELECT * FROM accounts ORDER BY account_no").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_account(account_no: str) -> dict[str, Any] | None:
    conn = db.get_connection()
    try:
        row = conn.execute("SELECT * FROM accounts WHERE account_no = ?", (account_no,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def ensure_term_period(year: int, term_index: int) -> None:
    _, start_date, end_date = vat_engine.term_date_range(year, term_index)
    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO fiscal_periods (
                year, period_type, period_no, start_date, end_date, is_locked
            ) VALUES (?, 'term', ?, ?, ?, 0)
            """,
            (year, term_index, start_date, end_date),
        )
        conn.commit()
    finally:
        conn.close()


def find_period_by_date(posting_date: str) -> dict[str, Any] | None:
    _parse_date(posting_date, "posting_date")
    conn = db.get_connection()
    try:
        row = conn.execute(
            """
            SELECT *
            FROM fiscal_periods
            WHERE period_type = 'term'
              AND ? BETWEEN start_date AND end_date
            ORDER BY start_date
            LIMIT 1
            """,
            (posting_date,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def is_locked_for_date(posting_date: str) -> bool:
    period = find_period_by_date(posting_date)
    return bool(period and period["is_locked"])


def lock_term(*, year: int, term_index: int, actor: str) -> dict[str, Any]:
    ensure_term_period(year, term_index)
    conn = db.get_connection()
    try:
        row = conn.execute(
            """
            SELECT *
            FROM fiscal_periods
            WHERE year = ? AND period_type = 'term' AND period_no = ?
            """,
            (year, term_index),
        ).fetchone()
        if row is None:
            raise LedgerError("Fant ikke termin for lasing")
        current = dict(row)
        if current["is_locked"]:
            return current
        conn.execute(
            """
            UPDATE fiscal_periods
            SET is_locked = 1, locked_at = CURRENT_TIMESTAMP, locked_by = ?
            WHERE id = ?
            """,
            (actor, current["id"]),
        )
        updated = conn.execute("SELECT * FROM fiscal_periods WHERE id = ?", (current["id"],)).fetchone()
        assert updated is not None
        updated_dict = dict(updated)
        _audit_log(
            conn,
            actor=actor,
            action="LOCK_TERM",
            entity_type="fiscal_period",
            entity_id=updated_dict["id"],
            before=current,
            after=updated_dict,
        )
        conn.commit()
        return updated_dict
    finally:
        conn.close()


def list_terms(year: int) -> list[dict[str, Any]]:
    for term_index, _ in vat_engine.term_choices():
        ensure_term_period(year, term_index)
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM fiscal_periods
            WHERE year = ? AND period_type = 'term'
            ORDER BY period_no
            """,
            (year,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _next_voucher_no(conn: sqlite3.Connection, series: str) -> int:
    conn.execute(
        """
        INSERT INTO voucher_sequences (series, last_no)
        VALUES (?, 0)
        ON CONFLICT(series) DO NOTHING
        """,
        (series,),
    )
    conn.execute("UPDATE voucher_sequences SET last_no = last_no + 1 WHERE series = ?", (series,))
    row = conn.execute("SELECT last_no FROM voucher_sequences WHERE series = ?", (series,)).fetchone()
    assert row is not None
    return int(row["last_no"])


def _normalize_line(raw: dict[str, Any], index: int) -> VoucherLineInput:
    account_no = str(raw.get("account_no", "")).strip()
    if not account_no:
        raise LedgerError(f"Linje {index}: account_no mangler")

    debit_nok = _to_int(raw.get("debit_nok", 0), f"Linje {index} debit_nok")
    credit_nok = _to_int(raw.get("credit_nok", 0), f"Linje {index} credit_nok")
    if debit_nok < 0 or credit_nok < 0:
        raise LedgerError(f"Linje {index}: debit/credit kan ikke vaere negativ")
    if (debit_nok == 0 and credit_nok == 0) or (debit_nok > 0 and credit_nok > 0):
        raise LedgerError(f"Linje {index}: ma ha verdi pa kun en side")

    vat_code = raw.get("vat_mva_code")
    vat_code = str(vat_code).strip() if vat_code else None

    vat_rate_raw = raw.get("vat_rate")
    vat_rate: float | None = None
    if vat_rate_raw not in (None, ""):
        try:
            vat_rate = float(vat_rate_raw)
        except (TypeError, ValueError) as exc:
            raise LedgerError(f"Linje {index}: ugyldig vat_rate") from exc
    vat_rate = vat_engine.to_decimal_rate(vat_rate)

    vat_base_raw = raw.get("vat_base_nok")
    vat_base_nok = None if vat_base_raw in (None, "") else _to_int(vat_base_raw, f"Linje {index} vat_base_nok")

    vat_amount_raw = raw.get("vat_amount_nok")
    vat_amount_nok = (
        None if vat_amount_raw in (None, "") else _to_int(vat_amount_raw, f"Linje {index} vat_amount_nok")
    )

    validation_errors = vat_engine.validate_vat_line_fields(
        vat_mva_code=vat_code,
        vat_rate=vat_rate,
        vat_base_nok=vat_base_nok,
        vat_amount_nok=vat_amount_nok,
    )
    if validation_errors:
        raise LedgerError(f"Linje {index}: " + "; ".join(validation_errors))

    bilag_raw = raw.get("bilag_id")
    bilag_id = None if bilag_raw in (None, "") else _to_int(bilag_raw, f"Linje {index} bilag_id")

    legacy_row_type = raw.get("legacy_row_type")
    legacy_row_type = str(legacy_row_type).strip() if legacy_row_type else None
    legacy_row_id_raw = raw.get("legacy_row_id")
    legacy_row_id = None if legacy_row_id_raw in (None, "") else _to_int(legacy_row_id_raw, f"Linje {index} legacy_row_id")

    return VoucherLineInput(
        account_no=account_no,
        debit_nok=debit_nok,
        credit_nok=credit_nok,
        description=str(raw.get("description", "") or "").strip(),
        vat_mva_code=vat_code,
        vat_rate=vat_rate,
        vat_base_nok=vat_base_nok,
        vat_amount_nok=vat_amount_nok,
        bilag_id=bilag_id,
        legacy_row_type=legacy_row_type,
        legacy_row_id=legacy_row_id,
    )


def _validate_accounts_exist(conn: sqlite3.Connection, lines: list[VoucherLineInput]) -> None:
    account_numbers = sorted({line.account_no for line in lines})
    rows = conn.execute(
        f"SELECT account_no, active FROM accounts WHERE account_no IN ({','.join('?' for _ in account_numbers)})",
        account_numbers,
    ).fetchall()
    found = {row["account_no"]: row["active"] for row in rows}
    missing = [acc for acc in account_numbers if acc not in found]
    if missing:
        raise LedgerError(f"Ukjente kontoer: {', '.join(missing)}")
    inactive = [acc for acc in account_numbers if found.get(acc) == 0]
    if inactive:
        raise LedgerError(f"Inaktive kontoer kan ikke brukes: {', '.join(inactive)}")


def _locked_for_posting(conn: sqlite3.Connection, posting_date: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM fiscal_periods
        WHERE period_type = 'term'
          AND is_locked = 1
          AND ? BETWEEN start_date AND end_date
        LIMIT 1
        """,
        (posting_date,),
    ).fetchone()
    return row is not None


def create_voucher(
    *,
    actor: str,
    voucher_type: str,
    document_date: str,
    posting_date: str,
    counterparty_name: str | None,
    counterparty_id: str | None,
    currency: str = "NOK",
    exchange_rate: float | None = None,
    description: str | None = None,
    bilag_id: int | None = None,
    lines: list[dict[str, Any]],
    series: str = "A",
    status: str = "posted",
    legacy_source: str | None = None,
    reversal_of_voucher_id: int | None = None,
    correction_of_voucher_id: int | None = None,
) -> int:
    if not lines:
        raise LedgerError("Voucher ma ha minst en linje")
    _parse_date(document_date, "document_date")
    _parse_date(posting_date, "posting_date")
    if voucher_type.strip().lower() != "reversal" and is_locked_for_date(posting_date):
        raise LedgerError("Perioden er last. Vanlige posteringer er ikke tillatt.")

    normalized_lines = [_normalize_line(raw, idx + 1) for idx, raw in enumerate(lines)]
    total_debit = sum(line.debit_nok for line in normalized_lines)
    total_credit = sum(line.credit_nok for line in normalized_lines)
    if total_debit != total_credit:
        raise LedgerError(f"Voucher er ubalansert (debet={total_debit}, kredit={total_credit})")

    conn = db.get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if voucher_type.strip().lower() != "reversal" and _locked_for_posting(conn, posting_date):
            raise LedgerError("Perioden er last. Vanlige posteringer er ikke tillatt.")
        _validate_accounts_exist(conn, normalized_lines)
        voucher_no = _next_voucher_no(conn, series)
        cursor = conn.execute(
            """
            INSERT INTO vouchers (
                voucher_series, voucher_no, voucher_type, document_date, posting_date,
                counterparty_name, counterparty_id, currency, exchange_rate, total_nok,
                created_by, status, bilag_id, description, legacy_source,
                reversal_of_voucher_id, correction_of_voucher_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                series,
                voucher_no,
                voucher_type,
                document_date,
                posting_date,
                (counterparty_name or "").strip() or None,
                (counterparty_id or "").strip() or None,
                currency,
                exchange_rate,
                total_debit,
                actor,
                status,
                bilag_id,
                (description or "").strip() or None,
                legacy_source,
                reversal_of_voucher_id,
                correction_of_voucher_id,
            ),
        )
        voucher_id = int(cursor.lastrowid)
        for line_no, line in enumerate(normalized_lines, start=1):
            conn.execute(
                """
                INSERT INTO voucher_lines (
                    voucher_id, line_no, account_no, debit_nok, credit_nok, description,
                    vat_mva_code, vat_rate, vat_base_nok, vat_amount_nok, bilag_id, legacy_row_type, legacy_row_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    voucher_id,
                    line_no,
                    line.account_no,
                    line.debit_nok,
                    line.credit_nok,
                    line.description,
                    line.vat_mva_code,
                    line.vat_rate,
                    line.vat_base_nok,
                    line.vat_amount_nok,
                    line.bilag_id,
                    line.legacy_row_type,
                    line.legacy_row_id,
                ),
            )
        _audit_log(
            conn,
            actor=actor,
            action="CREATE_VOUCHER",
            entity_type="voucher",
            entity_id=voucher_id,
            after={
                "voucher_no": voucher_no,
                "voucher_series": series,
                "voucher_type": voucher_type,
                "posting_date": posting_date,
                "total_nok": total_debit,
                "line_count": len(normalized_lines),
            },
        )
        conn.commit()
        return voucher_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_voucher(voucher_id: int) -> dict[str, Any] | None:
    conn = db.get_connection()
    try:
        header = conn.execute(
            """
            SELECT v.*, b.original_name AS bilag_original_name
            FROM vouchers v
            LEFT JOIN bilag_files b ON b.id = v.bilag_id
            WHERE v.id = ?
            """,
            (voucher_id,),
        ).fetchone()
        if header is None:
            return None
        lines = conn.execute(
            """
            SELECT vl.*, a.name AS account_name, b.original_name AS bilag_original_name
            FROM voucher_lines vl
            JOIN accounts a ON a.account_no = vl.account_no
            LEFT JOIN bilag_files b ON b.id = vl.bilag_id
            WHERE vl.voucher_id = ?
            ORDER BY vl.line_no
            """,
            (voucher_id,),
        ).fetchall()
        related = conn.execute(
            """
            SELECT id, voucher_series, voucher_no, voucher_type, posting_date, status
            FROM vouchers
            WHERE reversal_of_voucher_id = ? OR correction_of_voucher_id = ?
            ORDER BY id
            """,
            (voucher_id, voucher_id),
        ).fetchall()
        result = dict(header)
        result["lines"] = [dict(row) for row in lines]
        result["related_vouchers"] = [dict(row) for row in related]
        return result
    finally:
        conn.close()


def list_vouchers(
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    voucher_type: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            v.*,
            b.original_name AS bilag_original_name
        FROM vouchers v
        LEFT JOIN bilag_files b ON b.id = v.bilag_id
        WHERE 1 = 1
    """
    params: list[Any] = []
    if start_date:
        _parse_date(start_date, "start_date")
        sql += " AND v.posting_date >= ?"
        params.append(start_date)
    if end_date:
        _parse_date(end_date, "end_date")
        sql += " AND v.posting_date <= ?"
        params.append(end_date)
    if voucher_type:
        sql += " AND v.voucher_type = ?"
        params.append(voucher_type)
    sql += " ORDER BY v.posting_date DESC, v.voucher_no DESC LIMIT ?"
    params.append(limit)
    conn = db.get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def create_correction(
    *,
    actor: str,
    original_voucher_id: int,
    corrected_lines: list[dict[str, Any]],
    reason: str,
    correction_posting_date: str,
    correction_document_date: str | None = None,
) -> dict[str, int]:
    if not reason.strip():
        raise LedgerError("Aarsak for korreksjon er paakrevd")
    original = get_voucher(original_voucher_id)
    if original is None:
        raise LedgerError("Opprinnelig voucher finnes ikke")
    doc_date = correction_document_date or correction_posting_date

    original_lines = original["lines"]
    reversal_lines: list[dict[str, Any]] = []
    for line in original_lines:
        reversal_lines.append(
            {
                "account_no": line["account_no"],
                "debit_nok": int(line["credit_nok"]),
                "credit_nok": int(line["debit_nok"]),
                "description": f"Reversal av voucher {original['voucher_series']}-{original['voucher_no']} linje {line['line_no']}",
                "vat_mva_code": line["vat_mva_code"],
                "vat_rate": line["vat_rate"],
                "vat_base_nok": -int(line["vat_base_nok"]) if line["vat_base_nok"] is not None else None,
                "vat_amount_nok": -int(line["vat_amount_nok"]) if line["vat_amount_nok"] is not None else None,
                "bilag_id": line["bilag_id"],
            }
        )

    reversal_id = create_voucher(
        actor=actor,
        voucher_type="reversal",
        document_date=doc_date,
        posting_date=correction_posting_date,
        counterparty_name=original.get("counterparty_name"),
        counterparty_id=original.get("counterparty_id"),
        currency=original.get("currency") or "NOK",
        exchange_rate=original.get("exchange_rate"),
        description=f"Reversal av voucher {original['voucher_series']}-{original['voucher_no']}. {reason}",
        bilag_id=original.get("bilag_id"),
        lines=reversal_lines,
        series=original.get("voucher_series") or "A",
        status="reversed",
        reversal_of_voucher_id=original_voucher_id,
    )
    corrected_id = create_voucher(
        actor=actor,
        voucher_type="correction",
        document_date=doc_date,
        posting_date=correction_posting_date,
        counterparty_name=original.get("counterparty_name"),
        counterparty_id=original.get("counterparty_id"),
        currency=original.get("currency") or "NOK",
        exchange_rate=original.get("exchange_rate"),
        description=f"Korrigert voucher etter {original['voucher_series']}-{original['voucher_no']}. {reason}",
        bilag_id=original.get("bilag_id"),
        lines=corrected_lines,
        series=original.get("voucher_series") or "A",
        status="posted",
        correction_of_voucher_id=original_voucher_id,
    )

    conn = db.get_connection()
    try:
        _audit_log(
            conn,
            actor=actor,
            action="CREATE_CORRECTION",
            entity_type="voucher",
            entity_id=original_voucher_id,
            after={"reversal_voucher_id": reversal_id, "corrected_voucher_id": corrected_id},
            reason=reason,
        )
        conn.commit()
    finally:
        conn.close()

    return {"reversal_voucher_id": reversal_id, "corrected_voucher_id": corrected_id}


def journal_specification(start_date: str, end_date: str) -> list[dict[str, Any]]:
    _parse_date(start_date, "start_date")
    _parse_date(end_date, "end_date")
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                v.id AS voucher_id,
                v.voucher_series,
                v.voucher_no,
                v.voucher_type,
                v.document_date,
                v.posting_date,
                v.counterparty_name,
                v.description AS voucher_description,
                v.total_nok,
                vl.line_no,
                vl.account_no,
                a.name AS account_name,
                vl.debit_nok,
                vl.credit_nok,
                vl.description AS line_description,
                vl.vat_mva_code,
                vl.vat_rate,
                vl.vat_base_nok,
                vl.vat_amount_nok
            FROM vouchers v
            JOIN voucher_lines vl ON vl.voucher_id = v.id
            JOIN accounts a ON a.account_no = vl.account_no
            WHERE v.posting_date BETWEEN ? AND ?
            ORDER BY v.posting_date, v.voucher_no, vl.line_no
            """,
            (start_date, end_date),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def account_specification(start_date: str, end_date: str, account_no: str | None = None) -> list[dict[str, Any]]:
    _parse_date(start_date, "start_date")
    _parse_date(end_date, "end_date")
    params: list[Any] = [start_date, end_date]
    account_filter = ""
    if account_no:
        account_filter = " AND vl.account_no = ?"
        params.append(account_no)
    conn = db.get_connection()
    try:
        rows = conn.execute(
            f"""
            SELECT
                vl.account_no,
                a.name AS account_name,
                v.id AS voucher_id,
                v.voucher_series,
                v.voucher_no,
                v.posting_date,
                v.document_date,
                v.counterparty_name,
                vl.line_no,
                vl.debit_nok,
                vl.credit_nok,
                vl.description AS line_description
            FROM voucher_lines vl
            JOIN vouchers v ON v.id = vl.voucher_id
            JOIN accounts a ON a.account_no = vl.account_no
            WHERE v.posting_date BETWEEN ? AND ?
              {account_filter}
            ORDER BY vl.account_no, v.posting_date, v.voucher_no, vl.line_no
            """,
            params,
        ).fetchall()
        ledger_rows = [dict(row) for row in rows]
        running: dict[str, int] = {}
        for row in ledger_rows:
            acc = row["account_no"]
            running[acc] = running.get(acc, 0) + int(row["debit_nok"]) - int(row["credit_nok"])
            row["running_balance_nok"] = running[acc]
        return ledger_rows
    finally:
        conn.close()


def yearly_report_data_from_ledger(year: int) -> dict[str, Any]:
    conn = db.get_connection()
    try:
        sums = conn.execute(
            """
            SELECT
                a.account_type,
                SUM(vl.debit_nok) AS debit_sum,
                SUM(vl.credit_nok) AS credit_sum
            FROM voucher_lines vl
            JOIN vouchers v ON v.id = vl.voucher_id
            JOIN accounts a ON a.account_no = vl.account_no
            WHERE strftime('%Y', v.posting_date) = ?
            GROUP BY a.account_type
            """,
            (str(year),),
        ).fetchall()
        expense_breakdown_rows = conn.execute(
            """
            SELECT
                vl.account_no,
                a.name,
                SUM(vl.debit_nok - vl.credit_nok) AS amount_nok
            FROM voucher_lines vl
            JOIN vouchers v ON v.id = vl.voucher_id
            JOIN accounts a ON a.account_no = vl.account_no
            WHERE strftime('%Y', v.posting_date) = ?
              AND a.account_type = 'EXPENSE'
            GROUP BY vl.account_no, a.name
            ORDER BY vl.account_no
            """,
            (str(year),),
        ).fetchall()
        tx_rows = conn.execute(
            """
            SELECT
                v.posting_date AS date,
                v.voucher_series,
                v.voucher_no,
                v.voucher_type,
                v.counterparty_name,
                v.total_nok
            FROM vouchers v
            WHERE strftime('%Y', v.posting_date) = ?
            ORDER BY v.posting_date, v.voucher_no
            """,
            (str(year),),
        ).fetchall()
    finally:
        conn.close()

    income_total = 0
    expense_total = 0
    for row in sums:
        account_type = row["account_type"]
        debit_sum = int(row["debit_sum"] or 0)
        credit_sum = int(row["credit_sum"] or 0)
        if account_type == "INCOME":
            income_total += credit_sum - debit_sum
        elif account_type == "EXPENSE":
            expense_total += debit_sum - credit_sum

    category_totals = {f"{row['account_no']} {row['name']}": int(row["amount_nok"] or 0) for row in expense_breakdown_rows}
    transactions = [
        {
            "date": row["date"],
            "type": row["voucher_type"],
            "label": f"{row['voucher_series']}-{row['voucher_no']} {row['counterparty_name'] or ''}".strip(),
            "amount_nok": float(row["total_nok"]),
            "amount_original": float(row["total_nok"]),
            "currency": "NOK",
        }
        for row in tx_rows
    ]

    return {
        "year": year,
        "income_total_nok": float(income_total),
        "expense_total_nok": float(expense_total),
        "result_nok": float(income_total - expense_total),
        "category_totals": category_totals,
        "transactions": transactions,
        "missing_nok_count": 0,
    }


def today_iso() -> str:
    return date.today().isoformat()

