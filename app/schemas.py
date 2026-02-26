from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

from app.utils import calculate_nok_amount


class Currency(str, Enum):
    NOK = "NOK"
    EUR = "EUR"
    USD = "USD"


class ExpenseCategory(str, Enum):
    EQUIPMENT = "Utstyr"
    SOFTWARE = "Programvare/abonnement"
    MARKETING = "Markedsføring"
    TRAVEL = "Reise"
    PHONE = "Telefon/Internett"
    OFFICE = "Kontorrekvisita"
    OTHER = "Annet"


class PaymentMethod(str, Enum):
    CARD = "kort"
    VIPPS = "vipps"
    BANK = "bank"
    PAYPAL = "paypal"
    OTHER = "annet"


class BaseTransactionInput(BaseModel):
    date: str = Field(..., description="YYYY-MM-DD")
    amount_original: float = Field(..., gt=0)
    currency: Currency
    amount_nok: float | None = Field(default=None, ge=0)
    exchange_rate: float | None = Field(default=None, ge=0)
    note: str | None = Field(default="")

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        datetime.strptime(value, "%Y-%m-%d")
        return value

    @field_validator("note")
    @classmethod
    def strip_note(cls, value: str | None) -> str:
        return (value or "").strip()

    @model_validator(mode="after")
    def apply_amount_rules(self) -> "BaseTransactionInput":
        if self.exchange_rate == 0:
            self.exchange_rate = None
        # Accept manual NOK amount, manual exchange rate, or plain NOK amount.
        self.amount_nok = calculate_nok_amount(
            amount_original=self.amount_original,
            currency=self.currency.value,
            amount_nok=self.amount_nok,
            exchange_rate=self.exchange_rate,
        )
        return self


class IncomeInput(BaseTransactionInput):
    source: str = Field(..., min_length=2, max_length=120)

    @field_validator("source")
    @classmethod
    def normalize_source(cls, value: str) -> str:
        return value.strip()


class ExpenseInput(BaseTransactionInput):
    vendor: str = Field(..., min_length=2, max_length=150)
    category: ExpenseCategory
    vat_amount: float | None = Field(default=None, ge=0)
    payment_method: PaymentMethod

    @field_validator("vendor")
    @classmethod
    def normalize_vendor(cls, value: str) -> str:
        return value.strip()


class SettingsInput(BaseModel):
    company_name: str = Field(default="Eksempel ENK", min_length=2, max_length=150)
    org_number: str | None = Field(default="")
    default_currency: Currency = Currency.NOK
    default_vat_rate: float = Field(default=25.0, ge=0, le=100)
    default_output_vat_rate: float = Field(default=0.0, ge=0, le=100)
    primary_income_model: str = Field(
        default="Salg av digitale tjenester",
        min_length=3,
        max_length=200,
    )
    vat_registered_from: str | None = None

    @field_validator("company_name", "org_number", "primary_income_model")
    @classmethod
    def trim_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("vat_registered_from")
    @classmethod
    def validate_vat_date(cls, value: str | None) -> str | None:
        if not value:
            return None
        datetime.strptime(value, "%Y-%m-%d")
        return value
