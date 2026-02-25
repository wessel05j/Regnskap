from __future__ import annotations

import sqlite3

import pytest

from app import db, ledger, vat_engine


def _create_simple_income_voucher(posting_date: str = "2026-01-15", bilag_id: int | None = None) -> int:
    return ledger.create_voucher(
        actor="test",
        voucher_type="manual",
        document_date=posting_date,
        posting_date=posting_date,
        counterparty_name="Kunde AS",
        counterparty_id="",
        bilag_id=bilag_id,
        description="Test income",
        lines=[
            {
                "account_no": "1920",
                "debit_nok": 126,
                "credit_nok": 0,
                "description": "Innbetaling",
                "bilag_id": bilag_id,
            },
            {
                "account_no": "3000",
                "debit_nok": 0,
                "credit_nok": 101,
                "description": "Salg",
                "vat_mva_code": "3",
                "vat_rate": 0.25,
                "vat_base_nok": 101,
                "vat_amount_nok": 25,
                "bilag_id": bilag_id,
            },
            {
                "account_no": "2710",
                "debit_nok": 0,
                "credit_nok": 25,
                "description": "Utgaende MVA",
                "bilag_id": bilag_id,
            },
        ],
    )


def _create_simple_expense_voucher(posting_date: str = "2026-02-02") -> int:
    return ledger.create_voucher(
        actor="test",
        voucher_type="manual",
        document_date=posting_date,
        posting_date=posting_date,
        counterparty_name="Leverandor AS",
        counterparty_id="",
        description="Test expense",
        lines=[
            {
                "account_no": "5000",
                "debit_nok": 200,
                "credit_nok": 0,
                "description": "Kostnad",
            },
            {
                "account_no": "2720",
                "debit_nok": 50,
                "credit_nok": 0,
                "description": "Inngaende MVA",
                "vat_mva_code": "81",
                "vat_rate": 0.25,
                "vat_base_nok": 200,
                "vat_amount_nok": 50,
            },
            {"account_no": "1920", "debit_nok": 0, "credit_nok": 250, "description": "Betalt"},
        ],
    )


def test_voucher_requires_balance() -> None:
    with pytest.raises(ledger.LedgerError):
        ledger.create_voucher(
            actor="test",
            voucher_type="manual",
            document_date="2026-01-10",
            posting_date="2026-01-10",
            counterparty_name="X",
            counterparty_id="",
            description="Unbalanced",
            lines=[
                {"account_no": "1920", "debit_nok": 100, "credit_nok": 0},
                {"account_no": "3100", "debit_nok": 0, "credit_nok": 90},
            ],
        )


def test_lock_prevents_regular_posting_and_delete() -> None:
    conn = db.get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO bilag_files (stored_name, original_name, mime_type, file_size, sha256, uploaded_by)
            VALUES ('lock-test.pdf', 'lock-test.pdf', 'application/pdf', 10, 'lock123', 'test')
            """
        )
        bilag_id = int(cursor.lastrowid)
        conn.commit()
    finally:
        conn.close()

    voucher_id = _create_simple_income_voucher("2026-01-20", bilag_id=bilag_id)
    ledger.lock_term(year=2026, term_index=1, actor="admin")

    with pytest.raises(ledger.LedgerError):
        _create_simple_expense_voucher("2026-01-25")

    conn = db.get_connection()
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM vouchers WHERE id = ?", (voucher_id,))
            conn.commit()
    finally:
        conn.close()

    conn = db.get_connection()
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM bilag_files WHERE id = ?", (bilag_id,))
            conn.commit()
    finally:
        conn.close()


def test_correction_creates_reversal_and_corrected_voucher() -> None:
    original_id = _create_simple_income_voucher("2026-03-03")

    corrected_lines = [
        {"account_no": "1920", "debit_nok": 150, "credit_nok": 0, "description": "Innbetaling korrigert"},
        {
            "account_no": "3000",
            "debit_nok": 0,
            "credit_nok": 120,
            "description": "Salg korrigert",
            "vat_mva_code": "3",
            "vat_rate": 0.25,
            "vat_base_nok": 120,
            "vat_amount_nok": 30,
        },
        {"account_no": "2710", "debit_nok": 0, "credit_nok": 30, "description": "MVA korrigert"},
    ]
    result = ledger.create_correction(
        actor="admin",
        original_voucher_id=original_id,
        corrected_lines=corrected_lines,
        reason="Testkorreksjon",
        correction_posting_date="2026-03-10",
        correction_document_date="2026-03-10",
    )

    reversal = ledger.get_voucher(result["reversal_voucher_id"])
    corrected = ledger.get_voucher(result["corrected_voucher_id"])
    assert reversal is not None
    assert corrected is not None
    assert reversal["voucher_type"] == "reversal"
    assert reversal["status"] == "reversed"
    assert reversal["reversal_of_voucher_id"] == original_id
    assert corrected["voucher_type"] == "correction"
    assert corrected["correction_of_voucher_id"] == original_id
    assert int(reversal["lines"][0]["debit_nok"]) == 0
    assert int(reversal["lines"][0]["credit_nok"]) == 126


def test_vat_aggregation_whole_nok_and_floor_validation() -> None:
    _create_simple_income_voucher("2026-01-15")
    _create_simple_expense_voucher("2026-02-01")

    dataset = vat_engine.aggregate_vat_term(2026, 1)
    lines = {line["mvaKode"]: line for line in dataset["lines"]}
    assert "3" in lines
    assert "81" in lines
    assert lines["3"]["grunnlag_nok"] == 101
    assert lines["3"]["merverdiavgift_nok"] == 25
    assert isinstance(lines["3"]["grunnlag_nok"], int)
    assert isinstance(lines["3"]["merverdiavgift_nok"], int)
    assert dataset["validation_errors"] == []

    with pytest.raises(ledger.LedgerError):
        ledger.create_voucher(
            actor="test",
            voucher_type="manual",
            document_date="2026-01-30",
            posting_date="2026-01-30",
            counterparty_name="Bad VAT",
            counterparty_id="",
            description="invalid vat",
            lines=[
                {"account_no": "1920", "debit_nok": 126, "credit_nok": 0},
                {
                    "account_no": "3000",
                    "debit_nok": 0,
                    "credit_nok": 101,
                    "vat_mva_code": "3",
                    "vat_rate": 0.25,
                    "vat_base_nok": 101,
                    "vat_amount_nok": 26,
                },
                {"account_no": "2710", "debit_nok": 0, "credit_nok": 25},
            ],
        )


def test_vat_drilldown_contains_underlying_lines() -> None:
    conn = db.get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO bilag_files (stored_name, original_name, mime_type, file_size, sha256, uploaded_by)
            VALUES ('dummy.pdf', 'dummy.pdf', 'application/pdf', 10, 'abc123', 'test')
            """
        )
        bilag_id = int(cursor.lastrowid)
        conn.commit()
    finally:
        conn.close()

    ledger.create_voucher(
        actor="test",
        voucher_type="manual",
        document_date="2026-01-07",
        posting_date="2026-01-07",
        counterparty_name="Kunde Drill",
        counterparty_id="",
        bilag_id=bilag_id,
        description="drilldown test",
        lines=[
            {"account_no": "1920", "debit_nok": 125, "credit_nok": 0, "bilag_id": bilag_id},
            {
                "account_no": "3000",
                "debit_nok": 0,
                "credit_nok": 100,
                "vat_mva_code": "3",
                "vat_rate": 0.25,
                "vat_base_nok": 100,
                "vat_amount_nok": 25,
                "bilag_id": bilag_id,
            },
            {"account_no": "2710", "debit_nok": 0, "credit_nok": 25, "bilag_id": bilag_id},
        ],
    )

    dataset = vat_engine.aggregate_vat_term(2026, 1)
    code3 = [line for line in dataset["lines"] if line["mvaKode"] == "3"][0]
    assert len(code3["drilldown"]) == 1
    drill = code3["drilldown"][0]
    assert drill["voucher_ref"].startswith("A-")
    assert drill["bilag"] is not None
    assert drill["bilag"]["original_name"] == "dummy.pdf"
