from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from app import auth, db, ledger
from app.main import app


def _login_admin(client: TestClient) -> None:
    user_id = auth.create_user(username="admin", password="TestPassord123!", is_admin=True)
    token = auth.create_session(user_id=user_id)
    client.cookies.set("session_token", token)


def _create_income_voucher(posting_date: str) -> int:
    return ledger.create_voucher(
        actor="test",
        voucher_type="manual",
        document_date=posting_date,
        posting_date=posting_date,
        counterparty_name="Kunde AS",
        counterparty_id="",
        description="Testinntekt",
        lines=[
            {"account_no": "1920", "debit_nok": 1000, "credit_nok": 0, "description": "Innbetaling"},
            {"account_no": "3100", "debit_nok": 0, "credit_nok": 1000, "description": "Inntekt"},
        ],
    )


def test_navigation_routes_accessible_after_login() -> None:
    with TestClient(app) as client:
        _login_admin(client)
        routes = [
            "/",
            "/register",
            "/register/income",
            "/register/expense",
            "/vouchers",
            "/reports",
            "/reports?tab=vat",
            "/reports?tab=accounts",
            "/settings",
            "/settings/import-legacy",
            "/learn",
            "/learn/getting-started",
        ]
        for route in routes:
            response = client.get(route, follow_redirects=False)
            assert response.status_code == 200, f"Route feilet: {route}"


def test_reports_sidebar_active_state_is_single_and_correct() -> None:
    active_pattern = re.compile(r'href="([^"]+)" class="bg-indigo-50 text-indigo-700')
    with TestClient(app) as client:
        _login_admin(client)

        reports = client.get("/reports")
        active_reports = active_pattern.findall(reports.text)
        assert "/reports" in active_reports
        assert "/reports?tab=vat" not in active_reports
        assert "/reports?tab=accounts" not in active_reports

        vat = client.get("/reports?tab=vat")
        active_vat = active_pattern.findall(vat.text)
        assert "/reports?tab=vat" in active_vat
        assert "/reports" not in active_vat
        assert "/reports?tab=accounts" not in active_vat

        accounts = client.get("/reports?tab=accounts")
        active_accounts = active_pattern.findall(accounts.text)
        assert "/reports?tab=accounts" in active_accounts
        assert "/reports" not in active_accounts
        assert "/reports?tab=vat" not in active_accounts


def test_lock_term_route_still_blocks_posting() -> None:
    with TestClient(app) as client:
        _login_admin(client)
        response = client.post("/settings/lock-term", data={"year": "2026", "term": "1"}, follow_redirects=False)
        assert response.status_code == 303

        term_1 = [term for term in ledger.list_terms(2026) if int(term["period_no"]) == 1][0]
        assert term_1["is_locked"] == 1

        with pytest.raises(ledger.LedgerError):
            _create_income_voucher("2026-01-20")


def test_correction_flow_route_creates_reversal_and_corrected_voucher() -> None:
    with TestClient(app) as client:
        _login_admin(client)
        original_id = _create_income_voucher("2026-03-03")
        corrected_lines = [
            {"account_no": "1920", "debit_nok": 1500, "credit_nok": 0, "description": "Innbetaling korrigert"},
            {"account_no": "3100", "debit_nok": 0, "credit_nok": 1500, "description": "Inntekt korrigert"},
        ]

        response = client.post(
            f"/vouchers/{original_id}/correct",
            data={
                "reason": "Feil beløp",
                "posting_date": "2026-03-10",
                "document_date": "2026-03-10",
                "lines_json": json.dumps(corrected_lines),
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"].startswith("/vouchers/")

        conn = db.get_connection()
        try:
            rows = conn.execute(
                """
                SELECT voucher_type, reversal_of_voucher_id, correction_of_voucher_id
                FROM vouchers
                WHERE reversal_of_voucher_id = ? OR correction_of_voucher_id = ?
                ORDER BY id
                """,
                (original_id, original_id),
            ).fetchall()
        finally:
            conn.close()

        assert len(rows) == 2
        assert {str(row["voucher_type"]) for row in rows} == {"reversal", "correction"}


def test_simple_expense_route_creates_voucher() -> None:
    with TestClient(app) as client:
        _login_admin(client)

        response = client.post(
            "/register/expense",
            data={
                "date": "2026-04-07",
                "vendor": "Eleven Labs Inc.",
                "description": "Creator-abonnement",
                "total_amount_nok": "110,18",
                "vat_amount_nok": "",
                "expense_account": "5000",
                "settlement": "paid_now",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        voucher_id = int(response.headers["location"].rsplit("/", 1)[-1])
        voucher = ledger.get_voucher(voucher_id)
        assert voucher is not None
        assert voucher["counterparty_name"] == "Eleven Labs Inc."
        assert voucher["posting_date"] == "2026-04-07"
        assert int(voucher["total_nok"]) == 110
        assert "avrundet fra 110,18 NOK til 110 NOK" in str(voucher["description"])

        lines = {str(line["account_no"]): line for line in voucher["lines"]}
        assert int(lines["5000"]["debit_nok"]) == 110
        assert int(lines["1920"]["credit_nok"]) == 110


def test_simple_income_route_creates_vat_split() -> None:
    with TestClient(app) as client:
        _login_admin(client)

        response = client.post(
            "/register/income",
            data={
                "date": "2026-04-08",
                "customer": "Kunde AS",
                "description": "Videoprosjekt",
                "total_amount_nok": "1250",
                "income_vat": "vat25",
                "settlement": "paid_now",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        voucher_id = int(response.headers["location"].rsplit("/", 1)[-1])
        voucher = ledger.get_voucher(voucher_id)
        assert voucher is not None
        assert voucher["counterparty_name"] == "Kunde AS"
        assert int(voucher["total_nok"]) == 1250

        lines = {str(line["account_no"]): line for line in voucher["lines"]}
        assert int(lines["1920"]["debit_nok"]) == 1250
        assert int(lines["3000"]["credit_nok"]) == 1000
        assert int(lines["2710"]["credit_nok"]) == 250
        assert lines["3000"]["vat_mva_code"] == "3"
