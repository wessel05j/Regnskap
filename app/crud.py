from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Any

from app import db
from app.models import DashboardSummary
from app.schemas import ExpenseInput, IncomeInput, SettingsInput
from app.utils import TERM_RANGES, to_month_range


def _dict_rows(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def get_settings() -> dict[str, Any]:
    conn = db.get_connection()
    try:
        row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        if row is None:
            db.init_db()
            row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        return dict(row)
    finally:
        conn.close()


def update_settings(payload: SettingsInput) -> None:
    conn = db.get_connection()
    try:
        conn.execute(
            """
            UPDATE settings
            SET company_name = ?, org_number = ?, default_currency = ?, default_vat_rate = ?, default_output_vat_rate = ?,
                primary_income_model = ?, vat_registered_from = ?
            WHERE id = 1
            """,
            (
                payload.company_name,
                payload.org_number or "",
                payload.default_currency.value,
                payload.default_vat_rate,
                payload.default_output_vat_rate,
                payload.primary_income_model,
                payload.vat_registered_from,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def create_income(payload: IncomeInput, attachment_stored_name: str | None, attachment_original_name: str | None) -> int:
    conn = db.get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO incomes (
                date, amount_original, currency, amount_nok, exchange_rate, source, note,
                attachment_stored_name, attachment_original_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.date,
                payload.amount_original,
                payload.currency.value,
                payload.amount_nok,
                payload.exchange_rate,
                payload.source,
                payload.note,
                attachment_stored_name,
                attachment_original_name,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def update_income(
    income_id: int,
    payload: IncomeInput,
    attachment_stored_name: str | None,
    attachment_original_name: str | None,
    keep_existing_attachment: bool,
) -> None:
    current = get_income(income_id)
    if current is None:
        return

    stored = current["attachment_stored_name"] if keep_existing_attachment else attachment_stored_name
    original = current["attachment_original_name"] if keep_existing_attachment else attachment_original_name

    conn = db.get_connection()
    try:
        conn.execute(
            """
            UPDATE incomes
            SET date = ?, amount_original = ?, currency = ?, amount_nok = ?, exchange_rate = ?, source = ?, note = ?,
                attachment_stored_name = ?, attachment_original_name = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                payload.date,
                payload.amount_original,
                payload.currency.value,
                payload.amount_nok,
                payload.exchange_rate,
                payload.source,
                payload.note,
                stored,
                original,
                income_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_income(income_id: int) -> dict[str, Any] | None:
    conn = db.get_connection()
    try:
        row = conn.execute("SELECT * FROM incomes WHERE id = ?", (income_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_incomes(start_date: str | None, end_date: str | None, query: str | None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM incomes WHERE 1 = 1"
    params: list[Any] = []
    if start_date:
        sql += " AND date >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND date <= ?"
        params.append(end_date)
    if query:
        sql += " AND (source LIKE ? OR note LIKE ?)"
        like = f"%{query}%"
        params.extend([like, like])
    sql += " ORDER BY date DESC, id DESC"

    conn = db.get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
        return _dict_rows(rows)
    finally:
        conn.close()


def delete_income(income_id: int) -> None:
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM incomes WHERE id = ?", (income_id,))
        conn.commit()
    finally:
        conn.close()


def create_expense(payload: ExpenseInput, attachment_stored_name: str | None, attachment_original_name: str | None) -> int:
    conn = db.get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO expenses (
                date, vendor, category, amount_original, currency, amount_nok, exchange_rate,
                vat_amount, payment_method, note, attachment_stored_name, attachment_original_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.date,
                payload.vendor,
                payload.category.value,
                payload.amount_original,
                payload.currency.value,
                payload.amount_nok,
                payload.exchange_rate,
                payload.vat_amount,
                payload.payment_method.value,
                payload.note,
                attachment_stored_name,
                attachment_original_name,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def update_expense(
    expense_id: int,
    payload: ExpenseInput,
    attachment_stored_name: str | None,
    attachment_original_name: str | None,
    keep_existing_attachment: bool,
) -> None:
    current = get_expense(expense_id)
    if current is None:
        return

    stored = current["attachment_stored_name"] if keep_existing_attachment else attachment_stored_name
    original = current["attachment_original_name"] if keep_existing_attachment else attachment_original_name

    conn = db.get_connection()
    try:
        conn.execute(
            """
            UPDATE expenses
            SET date = ?, vendor = ?, category = ?, amount_original = ?, currency = ?, amount_nok = ?, exchange_rate = ?,
                vat_amount = ?, payment_method = ?, note = ?, attachment_stored_name = ?, attachment_original_name = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                payload.date,
                payload.vendor,
                payload.category.value,
                payload.amount_original,
                payload.currency.value,
                payload.amount_nok,
                payload.exchange_rate,
                payload.vat_amount,
                payload.payment_method.value,
                payload.note,
                stored,
                original,
                expense_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_expense(expense_id: int) -> dict[str, Any] | None:
    conn = db.get_connection()
    try:
        row = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_expenses(
    start_date: str | None,
    end_date: str | None,
    category: str | None,
    query: str | None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM expenses WHERE 1 = 1"
    params: list[Any] = []
    if start_date:
        sql += " AND date >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND date <= ?"
        params.append(end_date)
    if category:
        sql += " AND category = ?"
        params.append(category)
    if query:
        sql += " AND (vendor LIKE ? OR note LIKE ?)"
        like = f"%{query}%"
        params.extend([like, like])
    sql += " ORDER BY date DESC, id DESC"

    conn = db.get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
        return _dict_rows(rows)
    finally:
        conn.close()


def delete_expense(expense_id: int) -> None:
    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        conn.commit()
    finally:
        conn.close()


def _sum_nok(table_name: str, year: int) -> tuple[float, int]:
    conn = db.get_connection()
    try:
        rows = conn.execute(
            f"""
            SELECT amount_nok
            FROM {table_name}
            WHERE strftime('%Y', date) = ?
            """,
            (str(year),),
        ).fetchall()
    finally:
        conn.close()

    total = 0.0
    missing = 0
    for row in rows:
        amount = row["amount_nok"]
        if amount is None:
            missing += 1
            continue
        total += float(amount)
    return round(total, 2), missing


def get_dashboard_summary(year: int | None = None) -> DashboardSummary:
    if year is None:
        year = date.today().year

    income_total, missing_income = _sum_nok("incomes", year)
    expense_total, missing_expense = _sum_nok("expenses", year)

    return DashboardSummary(
        income_total_nok=income_total,
        expense_total_nok=expense_total,
        result_nok=round(income_total - expense_total, 2),
        missing_nok_count=missing_income + missing_expense,
    )


def list_latest_transactions(limit: int = 10) -> list[dict[str, Any]]:
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, date, amount_nok, amount_original, currency, 'income' AS type, source AS counterparty, note
            FROM incomes
            UNION ALL
            SELECT id, date, amount_nok, amount_original, currency, 'expense' AS type, vendor AS counterparty, note
            FROM expenses
            ORDER BY date DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return _dict_rows(rows)
    finally:
        conn.close()


def yearly_report_data(year: int) -> dict[str, Any]:
    conn = db.get_connection()
    try:
        incomes = _dict_rows(
            conn.execute(
                "SELECT * FROM incomes WHERE strftime('%Y', date) = ? ORDER BY date ASC, id ASC",
                (str(year),),
            ).fetchall()
        )
        expenses = _dict_rows(
            conn.execute(
                "SELECT * FROM expenses WHERE strftime('%Y', date) = ? ORDER BY date ASC, id ASC",
                (str(year),),
            ).fetchall()
        )
    finally:
        conn.close()

    income_total = 0.0
    expense_total = 0.0
    missing_nok: list[dict[str, Any]] = []
    category_totals: dict[str, float] = {}
    transactions: list[dict[str, Any]] = []

    for item in incomes:
        if item["amount_nok"] is None:
            missing_nok.append(item)
        else:
            income_total += float(item["amount_nok"])
        transactions.append(
            {
                "date": item["date"],
                "type": "Inntekt",
                "label": item["source"],
                "amount_nok": item["amount_nok"],
                "amount_original": item["amount_original"],
                "currency": item["currency"],
            }
        )

    for item in expenses:
        if item["amount_nok"] is None:
            missing_nok.append(item)
        else:
            expense_total += float(item["amount_nok"])
            category_totals[item["category"]] = round(category_totals.get(item["category"], 0.0) + float(item["amount_nok"]), 2)
        transactions.append(
            {
                "date": item["date"],
                "type": "Utgift",
                "label": item["category"],
                "amount_nok": item["amount_nok"],
                "amount_original": item["amount_original"],
                "currency": item["currency"],
            }
        )

    transactions.sort(key=lambda t: (t["date"], t["type"]))

    return {
        "year": year,
        "income_total_nok": round(income_total, 2),
        "expense_total_nok": round(expense_total, 2),
        "result_nok": round(income_total - expense_total, 2),
        "category_totals": category_totals,
        "transactions": transactions,
        "missing_nok_count": len(missing_nok),
    }


def term_report_data(year: int, term_index: int, outgoing_vat_rate_percent: float = 0.0) -> dict[str, Any]:
    term = to_month_range(term_index)
    conn = db.get_connection()
    try:
        incomes = _dict_rows(
            conn.execute(
                """
                SELECT * FROM incomes
                WHERE strftime('%Y', date) = ?
                AND CAST(strftime('%m', date) AS INTEGER) BETWEEN ? AND ?
                """,
                (str(year), term.month_start, term.month_end),
            ).fetchall()
        )
        expenses = _dict_rows(
            conn.execute(
                """
                SELECT * FROM expenses
                WHERE strftime('%Y', date) = ?
                AND CAST(strftime('%m', date) AS INTEGER) BETWEEN ? AND ?
                """,
                (str(year), term.month_start, term.month_end),
            ).fetchall()
        )
    finally:
        conn.close()

    turnover_nok = round(sum(float(item["amount_nok"]) for item in incomes if item["amount_nok"] is not None), 2)
    input_vat = round(sum(float(item["vat_amount"] or 0.0) for item in expenses), 2)
    output_vat = round(turnover_nok * (outgoing_vat_rate_percent / 100.0), 2)

    return {
        "year": year,
        "term_index": term_index,
        "term_label": term.label,
        "turnover_nok": turnover_nok,
        "output_vat_rate_percent": outgoing_vat_rate_percent,
        "output_vat": output_vat,
        "input_vat": input_vat,
        "net_vat_input_minus_output": round(input_vat - output_vat, 2),
        "net_vat_output_minus_input": round(output_vat - input_vat, 2),
    }


def available_years() -> list[int]:
    current_year = date.today().year
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT CAST(strftime('%Y', date) AS INTEGER) AS year_value
            FROM (
                SELECT date FROM incomes
                UNION ALL
                SELECT date FROM expenses
            )
            ORDER BY year_value DESC
            """
        ).fetchall()
    finally:
        conn.close()

    years = [int(r["year_value"]) for r in rows if r["year_value"] is not None]
    if current_year not in years:
        years.insert(0, current_year)
    return sorted(set(years), reverse=True)


def parse_year(value: str | None) -> int:
    if value is None or not value.strip():
        return date.today().year
    try:
        parsed = int(value)
    except ValueError:
        return date.today().year
    if parsed < 1900 or parsed > 2100:
        return date.today().year
    return parsed


def parse_term(value: str | None) -> int:
    if value is None or not value.strip():
        return 1
    parsed = int(value)
    if parsed < 1 or parsed > len(TERM_RANGES):
        raise ValueError("Ugyldig termin")
    return parsed


def format_now_for_filename() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")
