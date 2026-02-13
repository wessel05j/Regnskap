from __future__ import annotations

from app import crud, db, schemas


def main() -> None:
    db.init_db()

    income_1 = schemas.IncomeInput.model_validate(
        {
            "date": "2026-01-08",
            "amount_original": 12500,
            "currency": "NOK",
            "amount_nok": None,
            "exchange_rate": None,
            "source": "YouTube/Google AdSense",
            "note": "Januar utbetaling",
        }
    )
    income_2 = schemas.IncomeInput.model_validate(
        {
            "date": "2026-02-10",
            "amount_original": 1350,
            "currency": "USD",
            "amount_nok": 14300,
            "exchange_rate": None,
            "source": "Other",
            "note": "Samarbeid video",
        }
    )
    expense_1 = schemas.ExpenseInput.model_validate(
        {
            "date": "2026-01-12",
            "vendor": "Elkjop",
            "category": "Utstyr",
            "amount_original": 3999,
            "currency": "NOK",
            "amount_nok": None,
            "exchange_rate": None,
            "vat_amount": 799.8,
            "payment_method": "kort",
            "note": "Mikrofon",
        }
    )
    expense_2 = schemas.ExpenseInput.model_validate(
        {
            "date": "2026-02-05",
            "vendor": "Adobe",
            "category": "Programvare/abonnement",
            "amount_original": 59.99,
            "currency": "USD",
            "amount_nok": 640.0,
            "exchange_rate": None,
            "vat_amount": 0.0,
            "payment_method": "paypal",
            "note": "Maanedsabonnement",
        }
    )

    crud.create_income(income_1, None, None)
    crud.create_income(income_2, None, None)
    crud.create_expense(expense_1, None, None)
    crud.create_expense(expense_2, None, None)

    print("Demo-data lagt inn.")


if __name__ == "__main__":
    main()

