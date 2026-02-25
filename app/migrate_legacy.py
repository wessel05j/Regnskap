from __future__ import annotations

import argparse
import hashlib
import mimetypes
from pathlib import Path
from typing import Any

from app import db, ledger
from app.utils import calculate_nok_amount


def _to_int_nok(value: float | int | None) -> int | None:
    if value is None:
        return None
    return int(round(float(value)))


def _upsert_bilag_file(
    *,
    stored_name: str | None,
    original_name: str | None,
    actor: str,
) -> int | None:
    if not stored_name:
        return None
    file_path = db.ATTACHMENTS_DIR / stored_name
    if not file_path.exists() or not file_path.is_file():
        return None

    payload = file_path.read_bytes()
    sha256 = hashlib.sha256(payload).hexdigest()
    mime_type, _ = mimetypes.guess_type(file_path.name)
    conn = db.get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM bilag_files WHERE stored_name = ?",
            (stored_name,),
        ).fetchone()
        if existing:
            return int(existing["id"])

        cursor = conn.execute(
            """
            INSERT INTO bilag_files (
                stored_name, original_name, mime_type, file_size, sha256, uploaded_by
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                stored_name,
                (original_name or stored_name).strip(),
                mime_type or "application/octet-stream",
                len(payload),
                sha256,
                actor,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def _migrate_incomes(actor: str, output_vat_rate_percent: float) -> dict[str, int]:
    conn = db.get_connection()
    try:
        rows = conn.execute("SELECT * FROM incomes ORDER BY date, id").fetchall()
    finally:
        conn.close()

    migrated = 0
    skipped = 0
    output_rate = float(output_vat_rate_percent or 0.0) / 100.0
    for row in rows:
        legacy_source = f"income:{row['id']}"
        if _has_legacy_source(legacy_source):
            continue

        nok = calculate_nok_amount(
            amount_original=float(row["amount_original"]),
            currency=str(row["currency"]),
            amount_nok=row["amount_nok"],
            exchange_rate=row["exchange_rate"],
        )
        amount_nok = _to_int_nok(nok)
        if amount_nok is None or amount_nok <= 0:
            skipped += 1
            continue

        bilag_id = _upsert_bilag_file(
            stored_name=row["attachment_stored_name"],
            original_name=row["attachment_original_name"],
            actor=actor,
        )
        lines: list[dict[str, Any]]
        if output_rate > 0:
            vat_amount = int((amount_nok * output_rate) / (1.0 + output_rate))
            vat_base = amount_nok - vat_amount
            lines = [
                {
                    "account_no": "1920",
                    "debit_nok": amount_nok,
                    "credit_nok": 0,
                    "description": "Innbetaling",
                    "bilag_id": bilag_id,
                    "legacy_row_type": "income",
                    "legacy_row_id": row["id"],
                },
                {
                    "account_no": "3000",
                    "debit_nok": 0,
                    "credit_nok": vat_base,
                    "description": "Salgsinntekt",
                    "vat_mva_code": "3",
                    "vat_rate": output_rate,
                    "vat_base_nok": vat_base,
                    "vat_amount_nok": vat_amount,
                    "bilag_id": bilag_id,
                    "legacy_row_type": "income",
                    "legacy_row_id": row["id"],
                },
                {
                    "account_no": "2710",
                    "debit_nok": 0,
                    "credit_nok": vat_amount,
                    "description": "Utgaende MVA",
                    "bilag_id": bilag_id,
                    "legacy_row_type": "income",
                    "legacy_row_id": row["id"],
                },
            ]
        else:
            lines = [
                {
                    "account_no": "1920",
                    "debit_nok": amount_nok,
                    "credit_nok": 0,
                    "description": "Innbetaling",
                    "bilag_id": bilag_id,
                    "legacy_row_type": "income",
                    "legacy_row_id": row["id"],
                },
                {
                    "account_no": "3100",
                    "debit_nok": 0,
                    "credit_nok": amount_nok,
                    "description": "Salgsinntekt avgiftsfri",
                    "bilag_id": bilag_id,
                    "legacy_row_type": "income",
                    "legacy_row_id": row["id"],
                },
            ]

        ledger.create_voucher(
            actor=actor,
            voucher_type="legacy_income",
            document_date=row["date"],
            posting_date=row["date"],
            counterparty_name=row["source"],
            counterparty_id=None,
            currency=row["currency"],
            exchange_rate=row["exchange_rate"],
            description=row["note"] or "Migrert inntekt fra legacy-tabell",
            bilag_id=bilag_id,
            lines=lines,
            series="A",
            status="posted",
            legacy_source=legacy_source,
        )
        migrated += 1

    return {"migrated": migrated, "skipped": skipped}


def _expense_account_for_category(category: str) -> str:
    mapping = {
        "Utstyr": "4000",
        "Programvare/abonnement": "5000",
        "MarkedsfÃ¸ring": "5000",
        "Markedsforing": "5000",
        "Reise": "5000",
        "Telefon/Internett": "5000",
        "Kontorrekvisita": "5000",
        "Annet": "7790",
    }
    return mapping.get(category, "7790")


def _migrate_expenses(actor: str, input_vat_rate_percent: float) -> dict[str, int]:
    conn = db.get_connection()
    try:
        rows = conn.execute("SELECT * FROM expenses ORDER BY date, id").fetchall()
    finally:
        conn.close()

    migrated = 0
    skipped = 0
    input_rate = float(input_vat_rate_percent or 0.0) / 100.0
    for row in rows:
        legacy_source = f"expense:{row['id']}"
        if _has_legacy_source(legacy_source):
            continue

        nok = calculate_nok_amount(
            amount_original=float(row["amount_original"]),
            currency=str(row["currency"]),
            amount_nok=row["amount_nok"],
            exchange_rate=row["exchange_rate"],
        )
        amount_nok = _to_int_nok(nok)
        if amount_nok is None or amount_nok <= 0:
            skipped += 1
            continue

        vat_amount = _to_int_nok(row["vat_amount"])
        vat_amount = vat_amount if vat_amount and vat_amount > 0 else 0
        expense_net = amount_nok - vat_amount
        if expense_net <= 0:
            expense_net = amount_nok
            vat_amount = 0

        bilag_id = _upsert_bilag_file(
            stored_name=row["attachment_stored_name"],
            original_name=row["attachment_original_name"],
            actor=actor,
        )

        expense_account = _expense_account_for_category(str(row["category"]))
        lines: list[dict[str, Any]] = [
            {
                "account_no": expense_account,
                "debit_nok": expense_net,
                "credit_nok": 0,
                "description": f"Kostnad {row['category']}",
                "bilag_id": bilag_id,
                "legacy_row_type": "expense",
                "legacy_row_id": row["id"],
            },
        ]
        if vat_amount > 0:
            lines.append(
                {
                    "account_no": "2720",
                    "debit_nok": vat_amount,
                    "credit_nok": 0,
                    "description": "Inngaende MVA",
                    "vat_mva_code": "81",
                    "vat_rate": input_rate if input_rate > 0 else None,
                    "vat_base_nok": expense_net,
                    "vat_amount_nok": vat_amount,
                    "bilag_id": bilag_id,
                    "legacy_row_type": "expense",
                    "legacy_row_id": row["id"],
                }
            )
        lines.append(
            {
                "account_no": "1920",
                "debit_nok": 0,
                "credit_nok": amount_nok,
                "description": f"Utbetaling ({row['payment_method']})",
                "bilag_id": bilag_id,
                "legacy_row_type": "expense",
                "legacy_row_id": row["id"],
            }
        )

        ledger.create_voucher(
            actor=actor,
            voucher_type="legacy_expense",
            document_date=row["date"],
            posting_date=row["date"],
            counterparty_name=row["vendor"],
            counterparty_id=None,
            currency=row["currency"],
            exchange_rate=row["exchange_rate"],
            description=row["note"] or "Migrert utgift fra legacy-tabell",
            bilag_id=bilag_id,
            lines=lines,
            series="A",
            status="posted",
            legacy_source=legacy_source,
        )
        migrated += 1

    return {"migrated": migrated, "skipped": skipped}


def _has_legacy_source(legacy_source: str) -> bool:
    conn = db.get_connection()
    try:
        row = conn.execute("SELECT 1 FROM vouchers WHERE legacy_source = ? LIMIT 1", (legacy_source,)).fetchone()
        return row is not None
    finally:
        conn.close()


def run_legacy_migration(*, actor: str = "legacy-migration") -> dict[str, dict[str, int]]:
    db.init_db()
    conn = db.get_connection()
    try:
        settings_row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        output_rate = float((settings_row["default_output_vat_rate"] if settings_row else 0.0) or 0.0)
        input_rate = float((settings_row["default_vat_rate"] if settings_row else 25.0) or 25.0)
    finally:
        conn.close()

    incomes_result = _migrate_incomes(actor, output_rate)
    expenses_result = _migrate_expenses(actor, input_rate)
    return {"incomes": incomes_result, "expenses": expenses_result}


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrer legacy incomes/expenses til voucher-ledger.")
    parser.add_argument("--actor", default="legacy-migration", help="Navn som skrives i created_by/audit")
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()
    result = run_legacy_migration(actor=args.actor)
    print("Legacy-migrering fullfort.")
    print(f"Inntekter: migrert={result['incomes']['migrated']} skipped={result['incomes']['skipped']}")
    print(f"Utgifter: migrert={result['expenses']['migrated']} skipped={result['expenses']['skipped']}")


if __name__ == "__main__":
    main()

