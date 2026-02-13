from __future__ import annotations

from app import crud, schemas
from app.utils import calculate_nok_amount, sanitize_filename


def test_currency_conversion_with_exchange_rate() -> None:
    result = calculate_nok_amount(amount_original=100.0, currency="USD", amount_nok=None, exchange_rate=10.5)
    assert result == 1050.0


def test_year_summary_uses_nok_values() -> None:
    income = schemas.IncomeInput.model_validate(
        {
            "date": "2026-03-10",
            "amount_original": 1000,
            "currency": "NOK",
            "source": "YouTube/Google AdSense",
            "note": "",
        }
    )
    expense = schemas.ExpenseInput.model_validate(
        {
            "date": "2026-03-12",
            "vendor": "Komplett",
            "category": "Utstyr",
            "amount_original": 250,
            "currency": "NOK",
            "vat_amount": 50,
            "payment_method": "kort",
            "note": "",
        }
    )

    crud.create_income(income, None, None)
    crud.create_expense(expense, None, None)

    summary = crud.get_dashboard_summary(2026)
    assert summary.income_total_nok == 1000.0
    assert summary.expense_total_nok == 250.0
    assert summary.result_nok == 750.0


def test_term_summary_calculates_input_output_vat() -> None:
    income = schemas.IncomeInput.model_validate(
        {
            "date": "2026-01-15",
            "amount_original": 5000,
            "currency": "NOK",
            "source": "Other",
            "note": "",
        }
    )
    expense = schemas.ExpenseInput.model_validate(
        {
            "date": "2026-02-01",
            "vendor": "Telenor",
            "category": "Telefon/Internett",
            "amount_original": 1200,
            "currency": "NOK",
            "vat_amount": 240,
            "payment_method": "bank",
            "note": "",
        }
    )

    crud.create_income(income, None, None)
    crud.create_expense(expense, None, None)

    term = crud.term_report_data(year=2026, term_index=1, outgoing_vat_rate_percent=0.0)
    assert term["turnover_nok"] == 5000.0
    assert term["input_vat"] == 240.0
    assert term["output_vat"] == 0.0
    assert term["net_vat_input_minus_output"] == 240.0


def test_filename_sanitization_removes_unsafe_characters() -> None:
    cleaned = sanitize_filename("../../kvitt-ering @ 2026!.pdf")
    assert cleaned == "....kvitt-ering__2026.pdf"


def test_crud_create_and_read_income() -> None:
    income = schemas.IncomeInput.model_validate(
        {
            "date": "2026-05-20",
            "amount_original": 899,
            "currency": "EUR",
            "amount_nok": 10300,
            "source": "YouTube/Google AdSense",
            "note": "Test",
        }
    )
    income_id = crud.create_income(income, None, None)

    loaded = crud.get_income(income_id)
    assert loaded is not None
    assert loaded["source"] == "YouTube/Google AdSense"
    assert loaded["amount_nok"] == 10300.0
