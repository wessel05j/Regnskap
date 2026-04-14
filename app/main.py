from __future__ import annotations

import csv
import hashlib
import json
import logging
import mimetypes
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP
from datetime import date
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app import auth, crud, db, learn, ledger, legacy_import, migrate_legacy, pdf_reports, schemas, vat_engine
from app.utils import MAX_ATTACHMENT_SIZE, parse_float, sanitize_filename

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="Mini Regnskap ENK")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

LOGGER = logging.getLogger("regnskap")
MAX_LEGACY_DB_UPLOAD_SIZE = 200 * 1024 * 1024
LEGACY_UPLOADS_DIR = db.BACKUPS_DIR / "legacy_uploads"

SIMPLE_EXPENSE_ACCOUNT_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "5000", "label": "Vanlig driftskostnad", "hint": "programvare, abonnement, småkjøp"},
    {"value": "4000", "label": "Varekjøp", "hint": "varer du kjøper inn for virksomheten"},
    {"value": "7790", "label": "Annen kostnad", "hint": "brukes når de to andre ikke passer"},
)
SIMPLE_EXPENSE_ACCOUNT_LABELS = {item["value"]: item["label"] for item in SIMPLE_EXPENSE_ACCOUNT_OPTIONS}
SIMPLE_EXPENSE_SETTLEMENT_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "paid_now", "label": "Jeg har allerede betalt", "hint": "kort eller bankkonto"},
    {"value": "pay_later", "label": "Jeg skal betale senere", "hint": "føres som leverandørgjeld"},
)
SIMPLE_EXPENSE_SETTLEMENT_ACCOUNTS = {
    "paid_now": "1920",
    "pay_later": "2400",
}
SIMPLE_INCOME_SETTLEMENT_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "paid_now", "label": "Pengene er kommet inn", "hint": "bank eller kortoppgjør"},
    {"value": "invoice", "label": "Kunden skal betale senere", "hint": "føres som kundefordring"},
)
SIMPLE_INCOME_SETTLEMENT_ACCOUNTS = {
    "paid_now": "1920",
    "invoice": "1500",
}
SIMPLE_INCOME_VAT_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "none", "label": "Ingen MVA / usikker", "hint": "brukes for avgiftsfri eller usikker inntekt"},
    {"value": "vat25", "label": "25 % norsk MVA", "hint": "systemet deler totalen i salg og MVA"},
)


def setup_logging() -> None:
    db.ensure_data_dirs()
    logging.basicConfig(
        filename=str(db.LOG_FILE),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@app.on_event("startup")
def startup() -> None:
    setup_logging()
    startup_backup_path = None
    try:
        startup_backup_path = db.create_startup_backup()
    except Exception:
        LOGGER.exception("Oppstarts-backup feilet")
    db.init_db()
    LOGGER.info("Systemet startet")
    if startup_backup_path:
        LOGGER.info("Oppstarts-backup opprettet path=%s", startup_backup_path)


@app.middleware("http")
async def enforce_authentication(request: Request, call_next):  # type: ignore[override]
    path = request.url.path
    if path.startswith("/static"):
        return await call_next(request)

    token = request.cookies.get("session_token")
    user = auth.get_user_by_session_token(token)
    # Login is optional: run the app with a permissive default actor when no session exists.
    request.state.user = user or {"username": "system", "is_admin": 1}
    return await call_next(request)


def today_iso() -> str:
    return date.today().isoformat()


def enum_values(enum_cls: type) -> list[str]:
    return [item.value for item in enum_cls]  # type: ignore[attr-defined]


def form_errors(exc: ValidationError) -> dict[str, str]:
    result: dict[str, str] = {}
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"])
        result[loc] = err["msg"]
    return result


def current_actor(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is None:
        return "system"
    return str(user.get("username") or "system")


def require_admin(request: Request) -> None:
    user = getattr(request.state, "user", None)
    if not user or not bool(user.get("is_admin")):
        raise HTTPException(status_code=403, detail="Admin-rettigheter kreves")


def available_years_from_vouchers() -> list[int]:
    current_year = date.today().year
    conn = db.get_connection()
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT CAST(strftime('%Y', posting_date) AS INTEGER) AS year_value
            FROM vouchers
            ORDER BY year_value DESC
            """
        ).fetchall()
    finally:
        conn.close()
    years = [int(row["year_value"]) for row in rows if row["year_value"] is not None]
    if current_year not in years:
        years.append(current_year)
    return sorted(set(years), reverse=True)


def base_context(request: Request, active_nav: str) -> dict:
    return {
        "request": request,
        "active_nav": active_nav,
        "settings": crud.get_settings(),
        "disclaimer": "Internt system. Data er bokforingsgrunnlag, men ingen Altinn-innsending skjer automatisk.",
        "learn_tooltips": learn.TOOLTIPS,
        "current_user": getattr(request.state, "user", None),
    }


def simple_registration_context(request: Request, *, active_simple_form: str = "") -> dict:
    context = base_context(request, active_nav="register")
    context.update(
        {
            "active_simple_form": active_simple_form,
            "simple_expense_accounts": SIMPLE_EXPENSE_ACCOUNT_OPTIONS,
            "simple_expense_settlements": SIMPLE_EXPENSE_SETTLEMENT_OPTIONS,
            "simple_income_settlements": SIMPLE_INCOME_SETTLEMENT_OPTIONS,
            "simple_income_vat_options": SIMPLE_INCOME_VAT_OPTIONS,
        }
    )
    return context


def _normalize_nok_text(raw_value: str | None) -> str:
    return str(raw_value or "").strip().replace("\xa0", "").replace(" ", "").replace(",", ".")


def _parse_nok_amount(raw_value: str | None, field_label: str) -> tuple[Decimal, int]:
    text = _normalize_nok_text(raw_value)
    if not text:
        raise ValueError(f"{field_label} mangler.")
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{field_label} må være et tall.") from exc
    if amount <= 0:
        raise ValueError(f"{field_label} må være større enn 0.")
    rounded = int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return amount, rounded


def _parse_optional_nok_amount(raw_value: str | None, field_label: str) -> tuple[Decimal | None, int | None]:
    text = _normalize_nok_text(raw_value)
    if not text:
        return None, None
    amount, rounded = _parse_nok_amount(text, field_label)
    return amount, rounded


def _format_decimal_nok(amount: Decimal) -> str:
    return f"{amount:.2f}".replace(".", ",")


def _rounding_note(prefix: str, original_amount: Decimal | None, rounded_amount: int | None) -> str | None:
    if original_amount is None or rounded_amount is None:
        return None
    if original_amount == Decimal(rounded_amount):
        return None
    return (
        f"{prefix} avrundet fra {_format_decimal_nok(original_amount)} NOK til "
        f"{rounded_amount} NOK fordi denne versjonen lagrer hele kroner."
    )


def _combine_notes(*notes: str | None) -> str:
    return " | ".join(note for note in notes if note)


def _append_note(base_text: str, note: str | None) -> str:
    base = base_text.strip()
    if note and base:
        return f"{base} | {note}"
    if note:
        return note
    return base


def _split_total_with_vat(total_nok: int, rate_percent: int) -> tuple[int, int] | None:
    rate_decimal = vat_engine.to_decimal_rate(rate_percent)
    if rate_decimal is None or rate_decimal <= 0:
        return None
    normalized_rate = Decimal(str(rate_decimal))
    estimate = int(Decimal(total_nok) / (Decimal("1") + normalized_rate))
    window = max(10, int((Decimal("1") / normalized_rate).to_integral_value(rounding=ROUND_HALF_UP)) + 4)

    def _vat_amount(base_nok: int) -> int:
        return int((Decimal(base_nok) * normalized_rate).to_integral_value(rounding=ROUND_FLOOR))

    for base_nok in range(max(1, estimate - window), estimate + window + 1):
        vat_nok = _vat_amount(base_nok)
        if base_nok + vat_nok == total_nok:
            return base_nok, vat_nok

    for base_nok in range(1, total_nok + 1):
        vat_nok = _vat_amount(base_nok)
        if base_nok + vat_nok == total_nok:
            return base_nok, vat_nok
    return None


async def save_bilag(upload: UploadFile | None, actor: str) -> int | None:
    if upload is None or not upload.filename:
        return None

    payload = await upload.read()
    if len(payload) > MAX_ATTACHMENT_SIZE:
        raise HTTPException(status_code=400, detail="Vedlegg overstiger 10MB grense")

    original_name = sanitize_filename(upload.filename)
    suffix = Path(original_name).suffix.lower()
    allowed_suffixes = {".pdf", ".jpg", ".jpeg", ".png"}
    if suffix not in allowed_suffixes:
        raise HTTPException(status_code=400, detail="Ugyldig filtype. Tillatt: PDF, JPG, JPEG, PNG")

    stored_name = f"{uuid4().hex}{suffix}"
    file_path = db.ATTACHMENTS_DIR / stored_name
    file_path.write_bytes(payload)

    mime_type = upload.content_type or mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    sha256 = hashlib.sha256(payload).hexdigest()

    conn = db.get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO bilag_files (
                stored_name, original_name, mime_type, file_size, sha256, uploaded_by
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (stored_name, original_name, mime_type, len(payload), sha256, actor),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def write_csv_file(path: Path, header: list[str], rows: list[list[str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(header)
        writer.writerows(rows)
    return path


def resolve_reports_nav(tab: str | None) -> str:
    if tab == "vat":
        return "reports_vat"
    if tab == "accounts":
        return "reports_accounts"
    return "reports"


def normalize_reports_tab(tab: str | None) -> str:
    allowed = {"year", "vat", "journal", "accounts"}
    if tab and tab in allowed:
        return tab
    return "year"


async def save_legacy_upload(upload: UploadFile | None) -> Path | None:
    if upload is None or not upload.filename:
        return None
    original_name = sanitize_filename(upload.filename)
    suffix = Path(original_name).suffix.lower()
    if suffix not in {".db", ".sqlite", ".sqlite3"}:
        raise HTTPException(status_code=400, detail="Ugyldig filtype for legacy-import. Tillatt: .db, .sqlite, .sqlite3")
    payload = await upload.read()
    if len(payload) > MAX_LEGACY_DB_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="Legacy-fil overstiger 200MB grense")
    LEGACY_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    stored = LEGACY_UPLOADS_DIR / f"legacy_{uuid4().hex}{suffix}"
    stored.write_bytes(payload)
    return stored


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    context = {"request": request, "error": ""}
    return templates.TemplateResponse("login.html", context)


@app.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)) -> HTMLResponse:
    user = auth.authenticate_user(username, password)
    if user is None:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Feil brukernavn eller passord"},
            status_code=401,
        )
    session_token = auth.create_session(user_id=int(user["id"]))
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=False,
        samesite="lax",
    )
    return response


@app.get("/bootstrap-admin", response_class=HTMLResponse)
def bootstrap_admin_page(request: Request) -> HTMLResponse:
    if auth.has_any_users():
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse("bootstrap_admin.html", {"request": request, "error": ""})


@app.post("/bootstrap-admin", response_class=HTMLResponse)
def bootstrap_admin_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
) -> HTMLResponse:
    if auth.has_any_users():
        return RedirectResponse("/login", status_code=303)
    if password != password_confirm:
        return templates.TemplateResponse(
            "bootstrap_admin.html",
            {"request": request, "error": "Passordene er ikke like"},
            status_code=422,
        )
    try:
        user_id = auth.create_user(username=username, password=password, is_admin=True)
    except auth.AuthError as exc:
        return templates.TemplateResponse(
            "bootstrap_admin.html",
            {"request": request, "error": str(exc)},
            status_code=422,
        )
    session_token = auth.create_session(user_id=user_id)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=False,
        samesite="lax",
    )
    return response


@app.post("/logout")
def logout(request: Request) -> RedirectResponse:
    token = request.cookies.get("session_token")
    if token:
        auth.clear_session(token)
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("session_token")
    return response


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, year: str | None = None) -> HTMLResponse:
    selected_year = crud.parse_year(year)
    yearly = ledger.yearly_report_data_from_ledger(selected_year)
    latest_vouchers = ledger.list_vouchers(limit=10)
    latest_transactions = [
        {
            "date": row["posting_date"],
            "type": row["voucher_type"],
            "counterparty": row["counterparty_name"] or "-",
            "amount_nok": float(row["total_nok"]),
            "amount_original": float(row["total_nok"]),
            "currency": "NOK",
        }
        for row in latest_vouchers
    ]
    context = base_context(request, active_nav="dashboard")
    context.update(
        {
            "selected_year": selected_year,
            "years": available_years_from_vouchers(),
            "summary": {
                "income_total_nok": yearly["income_total_nok"],
                "expense_total_nok": yearly["expense_total_nok"],
                "result_nok": yearly["result_nok"],
                "missing_nok_count": 0,
            },
            "latest_transactions": latest_transactions,
        }
    )
    return templates.TemplateResponse("dashboard.html", context)


@app.get("/learn", response_class=HTMLResponse)
def learn_page(request: Request) -> HTMLResponse:
    context = base_context(request, active_nav="learn")
    context.update(
        {
            "glossary_entries": learn.GLOSSARY_ENTRIES,
            "getting_started_steps": learn.GETTING_STARTED_STEPS,
        }
    )
    return templates.TemplateResponse("learn.html", context)


@app.get("/learn/getting-started", response_class=HTMLResponse)
def getting_started_page(request: Request) -> HTMLResponse:
    context = base_context(request, active_nav="learn")
    context.update(
        {
            "glossary_entries": learn.GLOSSARY_ENTRIES,
            "getting_started_steps": learn.GETTING_STARTED_STEPS,
        }
    )
    return templates.TemplateResponse("getting_started.html", context)


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request) -> HTMLResponse:
    context = simple_registration_context(request)
    return templates.TemplateResponse("pages/register.html", context)


def _simple_income_defaults() -> dict[str, str]:
    return {
        "date": today_iso(),
        "customer": "",
        "description": "",
        "total_amount_nok": "",
        "income_vat": "none",
        "settlement": "paid_now",
    }


def _simple_expense_defaults() -> dict[str, str]:
    return {
        "date": today_iso(),
        "vendor": "",
        "description": "",
        "total_amount_nok": "",
        "vat_amount_nok": "",
        "expense_account": "5000",
        "settlement": "paid_now",
    }


def _render_simple_income_form(
    request: Request,
    *,
    form_data: dict[str, str],
    errors: dict[str, str],
    status_code: int = 200,
) -> HTMLResponse:
    context = simple_registration_context(request, active_simple_form="income")
    context.update({"form_data": form_data, "errors": errors})
    return templates.TemplateResponse("pages/simple_income_form.html", context, status_code=status_code)


def _render_simple_expense_form(
    request: Request,
    *,
    form_data: dict[str, str],
    errors: dict[str, str],
    status_code: int = 200,
) -> HTMLResponse:
    context = simple_registration_context(request, active_simple_form="expense")
    context.update({"form_data": form_data, "errors": errors})
    return templates.TemplateResponse("pages/simple_expense_form.html", context, status_code=status_code)


@app.get("/register/income", response_class=HTMLResponse)
def register_income_page(request: Request) -> HTMLResponse:
    return _render_simple_income_form(request, form_data=_simple_income_defaults(), errors={})


@app.post("/register/income", response_class=HTMLResponse)
async def register_income_submit(
    request: Request,
    entry_date: str = Form(..., alias="date"),
    customer: str = Form(...),
    description: str = Form(...),
    total_amount_nok: str = Form(...),
    income_vat: str = Form("none"),
    settlement: str = Form("paid_now"),
    attachment: UploadFile | None = File(default=None),
) -> HTMLResponse:
    form_data = {
        "date": entry_date,
        "customer": customer,
        "description": description,
        "total_amount_nok": total_amount_nok,
        "income_vat": income_vat,
        "settlement": settlement,
    }
    errors: dict[str, str] = {}
    actor = current_actor(request)

    try:
        date.fromisoformat(entry_date)
    except ValueError:
        errors["date"] = "Dato må være på formatet ÅÅÅÅ-MM-DD."

    if not customer.strip():
        errors["customer"] = "Skriv hvem som betalte deg."
    if not description.strip():
        errors["description"] = "Skriv kort hva inntekten gjelder."

    try:
        total_original, total_nok = _parse_nok_amount(total_amount_nok, "Beløp")
    except ValueError as exc:
        total_original, total_nok = None, None
        errors["total_amount_nok"] = str(exc)

    if income_vat not in {item["value"] for item in SIMPLE_INCOME_VAT_OPTIONS}:
        errors["income_vat"] = "Velg om inntekten har MVA eller ikke."
    if settlement not in SIMPLE_INCOME_SETTLEMENT_ACCOUNTS:
        errors["settlement"] = "Velg om pengene er kommet inn eller ikke."

    lines: list[dict[str, object]] = []
    if not errors and total_nok is not None:
        settlement_account = SIMPLE_INCOME_SETTLEMENT_ACCOUNTS[settlement]
        settlement_description = "Innbetalt" if settlement == "paid_now" else "Kundefordring"
        lines.append(
            {
                "account_no": settlement_account,
                "debit_nok": total_nok,
                "credit_nok": 0,
                "description": settlement_description,
            }
        )

        if income_vat == "none":
            lines.append(
                {
                    "account_no": "3100",
                    "debit_nok": 0,
                    "credit_nok": total_nok,
                    "description": description.strip(),
                }
            )
        else:
            split = _split_total_with_vat(total_nok, rate_percent=25)
            if split is None:
                errors["total_amount_nok"] = (
                    "Beløpet kan ikke deles i hele kroner med 25 % MVA i denne enkle visningen. "
                    "Bruk avansert bilag for dette beløpet."
                )
            else:
                sales_base_nok, vat_nok = split
                lines.extend(
                    [
                        {
                            "account_no": "3000",
                            "debit_nok": 0,
                            "credit_nok": sales_base_nok,
                            "description": description.strip(),
                            "vat_mva_code": "3",
                            "vat_rate": 0.25,
                            "vat_base_nok": sales_base_nok,
                            "vat_amount_nok": vat_nok,
                        },
                        {
                            "account_no": "2710",
                            "debit_nok": 0,
                            "credit_nok": vat_nok,
                            "description": "Utgående MVA",
                        },
                    ]
                )

    if not errors:
        rounding_note = _rounding_note("Beløpet", total_original, total_nok)
        voucher_description = _append_note(description, rounding_note)
        try:
            bilag_id = await save_bilag(attachment, actor)
            voucher_id = ledger.create_voucher(
                actor=actor,
                voucher_type="manual",
                document_date=entry_date,
                posting_date=entry_date,
                counterparty_name=customer,
                counterparty_id="",
                currency="NOK",
                description=voucher_description,
                bilag_id=bilag_id,
                lines=lines,
                series="A",
                status="posted",
            )
            return RedirectResponse(f"/vouchers/{voucher_id}", status_code=303)
        except ledger.LedgerError as exc:
            errors["ledger"] = str(exc)

    return _render_simple_income_form(request, form_data=form_data, errors=errors, status_code=422)


@app.get("/register/expense", response_class=HTMLResponse)
def register_expense_page(request: Request) -> HTMLResponse:
    return _render_simple_expense_form(request, form_data=_simple_expense_defaults(), errors={})


@app.post("/register/expense", response_class=HTMLResponse)
async def register_expense_submit(
    request: Request,
    entry_date: str = Form(..., alias="date"),
    vendor: str = Form(...),
    description: str = Form(...),
    total_amount_nok: str = Form(...),
    vat_amount_nok: str = Form(""),
    expense_account: str = Form("5000"),
    settlement: str = Form("paid_now"),
    attachment: UploadFile | None = File(default=None),
) -> HTMLResponse:
    form_data = {
        "date": entry_date,
        "vendor": vendor,
        "description": description,
        "total_amount_nok": total_amount_nok,
        "vat_amount_nok": vat_amount_nok,
        "expense_account": expense_account,
        "settlement": settlement,
    }
    errors: dict[str, str] = {}
    actor = current_actor(request)

    try:
        date.fromisoformat(entry_date)
    except ValueError:
        errors["date"] = "Dato må være på formatet ÅÅÅÅ-MM-DD."

    if not vendor.strip():
        errors["vendor"] = "Skriv hvem du betalte til."
    if not description.strip():
        errors["description"] = "Skriv kort hva du kjøpte."

    try:
        total_original, total_nok = _parse_nok_amount(total_amount_nok, "Totalt betalt")
    except ValueError as exc:
        total_original, total_nok = None, None
        errors["total_amount_nok"] = str(exc)

    try:
        vat_original, vat_nok = _parse_optional_nok_amount(vat_amount_nok, "MVA-beløp")
    except ValueError as exc:
        vat_original, vat_nok = None, None
        errors["vat_amount_nok"] = str(exc)

    if expense_account not in SIMPLE_EXPENSE_ACCOUNT_LABELS:
        errors["expense_account"] = "Velg typen utgift."
    if settlement not in SIMPLE_EXPENSE_SETTLEMENT_ACCOUNTS:
        errors["settlement"] = "Velg om utgiften er betalt eller ikke."
    if total_nok is not None and vat_nok is not None and vat_nok >= total_nok:
        errors["vat_amount_nok"] = "MVA-beløpet må være mindre enn totalbeløpet."

    lines = []
    if not errors and total_nok is not None:
        cost_nok = total_nok - (vat_nok or 0)
        if cost_nok <= 0:
            errors["total_amount_nok"] = "Kostnaden uten MVA må være større enn 0."
        else:
            lines.append(
                {
                    "account_no": expense_account,
                    "debit_nok": cost_nok,
                    "credit_nok": 0,
                    "description": description.strip(),
                }
            )
            if vat_nok:
                lines.append(
                    {
                        "account_no": "2720",
                        "debit_nok": vat_nok,
                        "credit_nok": 0,
                        "description": "Inngående MVA",
                        "vat_mva_code": "81",
                        "vat_rate": 0.25,
                        "vat_base_nok": cost_nok,
                        "vat_amount_nok": vat_nok,
                    }
                )
            lines.append(
                {
                    "account_no": SIMPLE_EXPENSE_SETTLEMENT_ACCOUNTS[settlement],
                    "debit_nok": 0,
                    "credit_nok": total_nok,
                    "description": "Betalt" if settlement == "paid_now" else "Leverandørgjeld",
                }
            )

    if not errors:
        rounding_note = _combine_notes(
            _rounding_note("Beløpet", total_original, total_nok),
            _rounding_note("MVA", vat_original, vat_nok),
        )
        voucher_description = _append_note(description, rounding_note)
        try:
            bilag_id = await save_bilag(attachment, actor)
            voucher_id = ledger.create_voucher(
                actor=actor,
                voucher_type="manual",
                document_date=entry_date,
                posting_date=entry_date,
                counterparty_name=vendor,
                counterparty_id="",
                currency="NOK",
                description=voucher_description,
                bilag_id=bilag_id,
                lines=lines,
                series="A",
                status="posted",
            )
            return RedirectResponse(f"/vouchers/{voucher_id}", status_code=303)
        except ledger.LedgerError as exc:
            errors["ledger"] = str(exc)

    return _render_simple_expense_form(request, form_data=form_data, errors=errors, status_code=422)


@app.get("/vouchers", response_class=HTMLResponse)
def vouchers_list(
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    voucher_type: str | None = None,
) -> HTMLResponse:
    rows = ledger.list_vouchers(start_date=start_date, end_date=end_date, voucher_type=voucher_type)
    context = base_context(request, active_nav="vouchers")
    context.update(
        {
            "rows": rows,
            "filters": {
                "start_date": start_date or "",
                "end_date": end_date or "",
                "voucher_type": voucher_type or "",
            },
        }
    )
    return templates.TemplateResponse("vouchers_list.html", context)


@app.get("/vouchers/new", response_class=HTMLResponse)
def vouchers_new(request: Request) -> HTMLResponse:
    context = base_context(request, active_nav="vouchers")
    context.update(
        {
            "form_data": {
                "voucher_type": "manual",
                "document_date": today_iso(),
                "posting_date": today_iso(),
                "counterparty_name": "",
                "counterparty_id": "",
                "currency": "NOK",
                "exchange_rate": "",
                "description": "",
                "series": "A",
                "status": "posted",
                "lines_json": json.dumps(
                    [
                        {"account_no": "1920", "debit_nok": 1000, "credit_nok": 0, "description": "Bank"},
                        {"account_no": "3100", "debit_nok": 0, "credit_nok": 1000, "description": "Salg"},
                    ],
                    indent=2,
                    ensure_ascii=False,
                ),
            },
            "errors": {},
            "accounts": ledger.list_accounts(active_only=True),
        }
    )
    return templates.TemplateResponse("voucher_form.html", context)


@app.post("/vouchers/new", response_class=HTMLResponse)
async def vouchers_create(
    request: Request,
    voucher_type: str = Form("manual"),
    document_date: str = Form(...),
    posting_date: str = Form(...),
    counterparty_name: str = Form(""),
    counterparty_id: str = Form(""),
    currency: str = Form("NOK"),
    exchange_rate: str = Form(""),
    description: str = Form(""),
    series: str = Form("A"),
    status: str = Form("posted"),
    lines_json: str = Form(...),
    attachment: UploadFile | None = File(default=None),
) -> HTMLResponse:
    actor = current_actor(request)
    errors: dict[str, str] = {}
    try:
        lines = json.loads(lines_json)
        if not isinstance(lines, list):
            raise ValueError("lines_json ma vaere en JSON-liste")
    except (ValueError, json.JSONDecodeError):
        errors["lines_json"] = "Ugyldig JSON-format for linjer."
        lines = []

    bilag_id = None
    if not errors:
        bilag_id = await save_bilag(attachment, actor=actor)

    if not errors:
        try:
            voucher_id = ledger.create_voucher(
                actor=actor,
                voucher_type=voucher_type.strip() or "manual",
                document_date=document_date,
                posting_date=posting_date,
                counterparty_name=counterparty_name,
                counterparty_id=counterparty_id,
                currency=currency,
                exchange_rate=parse_float(exchange_rate),
                description=description,
                bilag_id=bilag_id,
                lines=lines,
                series=series.strip() or "A",
                status=status,
            )
            LOGGER.info("Ny voucher registrert id=%s", voucher_id)
            return RedirectResponse(f"/vouchers/{voucher_id}", status_code=303)
        except ledger.LedgerError as exc:
            errors["ledger"] = str(exc)

    context = base_context(request, active_nav="vouchers")
    context.update(
        {
            "form_data": {
                "voucher_type": voucher_type,
                "document_date": document_date,
                "posting_date": posting_date,
                "counterparty_name": counterparty_name,
                "counterparty_id": counterparty_id,
                "currency": currency,
                "exchange_rate": exchange_rate,
                "description": description,
                "series": series,
                "status": status,
                "lines_json": lines_json,
            },
            "errors": errors,
            "accounts": ledger.list_accounts(active_only=True),
        }
    )
    return templates.TemplateResponse("voucher_form.html", context, status_code=422)


@app.get("/vouchers/{voucher_id}", response_class=HTMLResponse)
def voucher_detail(request: Request, voucher_id: int) -> HTMLResponse:
    voucher = ledger.get_voucher(voucher_id)
    if voucher is None:
        raise HTTPException(status_code=404, detail="Voucher ikke funnet")
    context = base_context(request, active_nav="vouchers")
    context.update({"voucher": voucher})
    return templates.TemplateResponse("voucher_detail.html", context)


@app.get("/vouchers/{voucher_id}/correct", response_class=HTMLResponse)
def voucher_correct_page(request: Request, voucher_id: int) -> HTMLResponse:
    voucher = ledger.get_voucher(voucher_id)
    if voucher is None:
        raise HTTPException(status_code=404, detail="Voucher ikke funnet")
    prefilled_lines = [
        {
            "account_no": line["account_no"],
            "debit_nok": int(line["debit_nok"]),
            "credit_nok": int(line["credit_nok"]),
            "description": line["description"] or "",
            "vat_mva_code": line["vat_mva_code"],
            "vat_rate": line["vat_rate"],
            "vat_base_nok": line["vat_base_nok"],
            "vat_amount_nok": line["vat_amount_nok"],
            "bilag_id": line["bilag_id"],
        }
        for line in voucher["lines"]
    ]
    context = base_context(request, active_nav="vouchers")
    context.update(
        {
            "voucher": voucher,
            "form_data": {
                "reason": "",
                "posting_date": today_iso(),
                "document_date": today_iso(),
                "lines_json": json.dumps(prefilled_lines, indent=2, ensure_ascii=False),
            },
            "errors": {},
        }
    )
    return templates.TemplateResponse("voucher_correct.html", context)


@app.post("/vouchers/{voucher_id}/correct", response_class=HTMLResponse)
def voucher_correct_submit(
    request: Request,
    voucher_id: int,
    reason: str = Form(...),
    posting_date: str = Form(...),
    document_date: str = Form(...),
    lines_json: str = Form(...),
) -> HTMLResponse:
    voucher = ledger.get_voucher(voucher_id)
    if voucher is None:
        raise HTTPException(status_code=404, detail="Voucher ikke funnet")

    errors: dict[str, str] = {}
    try:
        lines = json.loads(lines_json)
        if not isinstance(lines, list):
            raise ValueError("lines_json ma vaere liste")
    except (ValueError, json.JSONDecodeError):
        lines = []
        errors["lines_json"] = "Ugyldig JSON-format for linjer."

    if not errors:
        try:
            result = ledger.create_correction(
                actor=current_actor(request),
                original_voucher_id=voucher_id,
                corrected_lines=lines,
                reason=reason,
                correction_posting_date=posting_date,
                correction_document_date=document_date,
            )
            LOGGER.info(
                "Korreksjon opprettet for voucher=%s reversal=%s corrected=%s",
                voucher_id,
                result["reversal_voucher_id"],
                result["corrected_voucher_id"],
            )
            return RedirectResponse(f"/vouchers/{result['corrected_voucher_id']}", status_code=303)
        except ledger.LedgerError as exc:
            errors["ledger"] = str(exc)

    context = base_context(request, active_nav="vouchers")
    context.update(
        {
            "voucher": voucher,
            "form_data": {
                "reason": reason,
                "posting_date": posting_date,
                "document_date": document_date,
                "lines_json": lines_json,
            },
            "errors": errors,
        }
    )
    return templates.TemplateResponse("voucher_correct.html", context, status_code=422)


@app.get("/incomes", response_class=HTMLResponse)
def incomes_list(
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    q: str | None = None,
) -> HTMLResponse:
    rows = crud.list_incomes(start_date=start_date, end_date=end_date, query=q)
    context = base_context(request, active_nav="incomes")
    context.update(
        {
            "rows": rows,
            "legacy_read_only": True,
            "filters": {"start_date": start_date or "", "end_date": end_date or "", "q": q or ""},
        }
    )
    return templates.TemplateResponse("incomes_list.html", context)


@app.get("/expenses", response_class=HTMLResponse)
def expenses_list(
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
    q: str | None = None,
) -> HTMLResponse:
    rows = crud.list_expenses(start_date=start_date, end_date=end_date, category=category, query=q)
    context = base_context(request, active_nav="expenses")
    context.update(
        {
            "rows": rows,
            "legacy_read_only": True,
            "filters": {
                "start_date": start_date or "",
                "end_date": end_date or "",
                "category": category or "",
                "q": q or "",
            },
            "categories": enum_values(schemas.ExpenseCategory),
        }
    )
    return templates.TemplateResponse("expenses_list.html", context)


def _legacy_write_blocked() -> None:
    raise HTTPException(status_code=403, detail="Legacy-tabeller er skrivebeskyttet etter ledger-migrering.")


@app.get("/incomes/new")
def income_new_blocked() -> None:
    _legacy_write_blocked()


@app.post("/incomes/new")
def income_create_blocked() -> None:
    _legacy_write_blocked()


@app.get("/incomes/{income_id}/edit")
def income_edit_blocked(income_id: int) -> None:  # noqa: ARG001
    _legacy_write_blocked()


@app.post("/incomes/{income_id}/edit")
def income_update_blocked(income_id: int) -> None:  # noqa: ARG001
    _legacy_write_blocked()


@app.post("/incomes/{income_id}/delete")
def income_delete_blocked(income_id: int) -> None:  # noqa: ARG001
    _legacy_write_blocked()


@app.get("/expenses/new")
def expense_new_blocked() -> None:
    _legacy_write_blocked()


@app.post("/expenses/new")
def expense_create_blocked() -> None:
    _legacy_write_blocked()


@app.get("/expenses/{expense_id}/edit")
def expense_edit_blocked(expense_id: int) -> None:  # noqa: ARG001
    _legacy_write_blocked()


@app.post("/expenses/{expense_id}/edit")
def expense_update_blocked(expense_id: int) -> None:  # noqa: ARG001
    _legacy_write_blocked()


@app.post("/expenses/{expense_id}/delete")
def expense_delete_blocked(expense_id: int) -> None:  # noqa: ARG001
    _legacy_write_blocked()


@app.get("/reports", response_class=HTMLResponse)
def reports_page(
    request: Request,
    year: str | None = None,
    term: str | None = None,
    tab: str | None = None,
) -> HTMLResponse:
    selected_year = crud.parse_year(year)
    try:
        selected_term = crud.parse_term(term)
    except Exception:
        selected_term = 1
    selected_tab = normalize_reports_tab(tab)
    year_data = ledger.yearly_report_data_from_ledger(selected_year)
    vat_data = vat_engine.aggregate_vat_term(selected_year, selected_term)
    context = base_context(request, active_nav=resolve_reports_nav(tab))
    context.update(
        {
            "years": available_years_from_vouchers(),
            "selected_year": selected_year,
            "selected_term": selected_term,
            "selected_report_tab": selected_tab,
            "terms": vat_engine.term_choices(),
            "year_data": year_data,
            "vat_data": vat_data,
            "today_iso": today_iso(),
        }
    )
    return templates.TemplateResponse("reports.html", context)


@app.post("/reports/yearly")
def reports_yearly(year: int = Form(...)) -> FileResponse:
    settings = crud.get_settings()
    data = ledger.yearly_report_data_from_ledger(year)
    output = pdf_reports.yearly_report_output_path(year, crud.format_now_for_filename())
    pdf_reports.generate_yearly_report_pdf(data, settings, output)
    LOGGER.info("Arsrapport generert for ar=%s", year)
    return FileResponse(path=output, filename=output.name, media_type="application/pdf")


@app.post("/reports/mva")
def reports_term_pdf(year: int = Form(...), term: int = Form(...)) -> FileResponse:
    settings = crud.get_settings()
    data = vat_engine.aggregate_vat_term(year, term)
    output = pdf_reports.term_report_output_path(year, term, crud.format_now_for_filename())
    pdf_reports.generate_term_report_pdf(data, settings, output)
    LOGGER.info("MVA-rapport generert for ar=%s termin=%s", year, term)
    return FileResponse(path=output, filename=output.name, media_type="application/pdf")


@app.post("/reports/mva/json")
def reports_term_json(year: int = Form(...), term: int = Form(...)) -> FileResponse:
    output = vat_engine.export_vat_term_dataset_json(year, term, db.REPORTS_DIR)
    return FileResponse(path=output, filename=output.name, media_type="application/json")


@app.post("/reports/mva/csv")
def reports_term_csv(year: int = Form(...), term: int = Form(...)) -> FileResponse:
    dataset = vat_engine.aggregate_vat_term(year, term)
    filename = f"mva_spes_{year}_t{term}_{crud.format_now_for_filename()}.csv"
    output = db.REPORTS_DIR / filename
    rows = [
        [
            str(line["mvaKode"]),
            "" if line["sats"] is None else f"{line['sats'] * 100:.2f}",
            str(int(line["grunnlag_nok"])),
            str(int(line["merverdiavgift_nok"])),
        ]
        for line in dataset["lines"]
    ]
    write_csv_file(output, ["mvaKode", "sats_prosent", "grunnlag_nok", "merverdiavgift_nok"], rows)
    return FileResponse(path=output, filename=output.name, media_type="text/csv")


@app.get("/reports/mva/drilldown")
def reports_term_drilldown(year: int, term: int, mva_code: str) -> JSONResponse:
    dataset = vat_engine.aggregate_vat_term(year, term)
    matched = [line for line in dataset["lines"] if line["mvaKode"] == mva_code]
    if not matched:
        raise HTTPException(status_code=404, detail="Fant ingen linjer for valgt mvaKode")
    return JSONResponse({"year": year, "term": term, "mva_code": mva_code, "lines": matched})


@app.post("/reports/journal/pdf")
def reports_journal_pdf(start_date: str = Form(...), end_date: str = Form(...)) -> FileResponse:
    settings = crud.get_settings()
    rows = ledger.journal_specification(start_date, end_date)
    output = pdf_reports.journal_report_output_path(start_date, end_date, crud.format_now_for_filename())
    pdf_reports.generate_journal_pdf(rows, settings, output, start_date=start_date, end_date=end_date)
    return FileResponse(path=output, filename=output.name, media_type="application/pdf")


@app.post("/reports/journal/csv")
def reports_journal_csv(start_date: str = Form(...), end_date: str = Form(...)) -> FileResponse:
    rows = ledger.journal_specification(start_date, end_date)
    output = db.REPORTS_DIR / f"bokforing_{start_date}_{end_date}_{crud.format_now_for_filename()}.csv"
    csv_rows = [
        [
            row["posting_date"],
            f"{row['voucher_series']}-{row['voucher_no']}",
            str(row["line_no"]),
            row["account_no"],
            row["account_name"],
            str(row["debit_nok"]),
            str(row["credit_nok"]),
            row["line_description"] or "",
            row["vat_mva_code"] or "",
            "" if row["vat_rate"] is None else f"{float(row['vat_rate']) * 100:.2f}",
            "" if row["vat_base_nok"] is None else str(row["vat_base_nok"]),
            "" if row["vat_amount_nok"] is None else str(row["vat_amount_nok"]),
        ]
        for row in rows
    ]
    write_csv_file(
        output,
        [
            "posting_date",
            "voucher_ref",
            "line_no",
            "account_no",
            "account_name",
            "debit_nok",
            "credit_nok",
            "description",
            "mva_code",
            "vat_rate_percent",
            "vat_base_nok",
            "vat_amount_nok",
        ],
        csv_rows,
    )
    return FileResponse(path=output, filename=output.name, media_type="text/csv")


@app.post("/reports/accounts/pdf")
def reports_account_pdf(
    start_date: str = Form(...),
    end_date: str = Form(...),
    account_no: str = Form(""),
) -> FileResponse:
    settings = crud.get_settings()
    rows = ledger.account_specification(start_date, end_date, account_no.strip() or None)
    output = pdf_reports.account_report_output_path(start_date, end_date, crud.format_now_for_filename())
    pdf_reports.generate_account_spec_pdf(
        rows,
        settings,
        output,
        start_date=start_date,
        end_date=end_date,
        account_no=account_no.strip() or None,
    )
    return FileResponse(path=output, filename=output.name, media_type="application/pdf")


@app.post("/reports/accounts/csv")
def reports_account_csv(
    start_date: str = Form(...),
    end_date: str = Form(...),
    account_no: str = Form(""),
) -> FileResponse:
    rows = ledger.account_specification(start_date, end_date, account_no.strip() or None)
    output = db.REPORTS_DIR / f"kontospes_{start_date}_{end_date}_{crud.format_now_for_filename()}.csv"
    csv_rows = [
        [
            row["account_no"],
            row["account_name"],
            row["posting_date"],
            f"{row['voucher_series']}-{row['voucher_no']}",
            str(row["line_no"]),
            str(row["debit_nok"]),
            str(row["credit_nok"]),
            str(row["running_balance_nok"]),
            row["line_description"] or "",
        ]
        for row in rows
    ]
    write_csv_file(
        output,
        [
            "account_no",
            "account_name",
            "posting_date",
            "voucher_ref",
            "line_no",
            "debit_nok",
            "credit_nok",
            "running_balance_nok",
            "description",
        ],
        csv_rows,
    )
    return FileResponse(path=output, filename=output.name, media_type="text/csv")


def legacy_import_page_context(
    request: Request,
    *,
    form_data: dict[str, str] | None = None,
    preview: dict | None = None,
    import_result: dict | None = None,
    errors: list[str] | None = None,
    success_message: str = "",
) -> dict:
    candidates = legacy_import.discover_legacy_candidates()
    context = base_context(request, active_nav="settings")
    context.update(
        {
            "candidate_paths": [str(path) for path in candidates],
            "form_data": form_data or {"db_path": "", "source_path": "", "import_settings": "0"},
            "preview": preview,
            "import_result": import_result,
            "errors": errors or [],
            "success_message": success_message,
            "no_candidates_found": len(candidates) == 0,
            "current_db_path": str(db.get_db_path().resolve()),
            "backups_dir_path": str(db.BACKUPS_DIR.resolve()),
        }
    )
    return context


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, year: str | None = None) -> HTMLResponse:
    selected_year = crud.parse_year(year)
    terms = ledger.list_terms(selected_year)
    current = crud.get_settings()
    context = base_context(request, active_nav="settings")
    context.update(
        {
            "form_data": current,
            "errors": {},
            "currencies": enum_values(schemas.Currency),
            "selected_year": selected_year,
            "term_rows": terms,
            "years": available_years_from_vouchers(),
        }
    )
    return templates.TemplateResponse("settings.html", context)


@app.post("/settings", response_class=HTMLResponse)
def settings_update(
    request: Request,
    company_name: str = Form(...),
    org_number: str = Form(""),
    default_currency: str = Form("NOK"),
    default_vat_rate: float = Form(25.0),
    default_output_vat_rate: float = Form(0.0),
    primary_income_model: str = Form(...),
    vat_registered_from: str = Form(""),
) -> HTMLResponse:
    input_data = {
        "company_name": company_name,
        "org_number": org_number,
        "default_currency": default_currency,
        "default_vat_rate": default_vat_rate,
        "default_output_vat_rate": default_output_vat_rate,
        "primary_income_model": primary_income_model,
        "vat_registered_from": vat_registered_from,
    }

    try:
        payload = schemas.SettingsInput.model_validate(input_data)
        crud.update_settings(payload)
        LOGGER.info("Settings oppdatert")
        return RedirectResponse("/settings", status_code=303)
    except ValidationError as exc:
        selected_year = date.today().year
        context = base_context(request, active_nav="settings")
        context.update(
            {
                "form_data": input_data,
                "errors": form_errors(exc),
                "currencies": enum_values(schemas.Currency),
                "selected_year": selected_year,
                "term_rows": ledger.list_terms(selected_year),
                "years": available_years_from_vouchers(),
            }
        )
        return templates.TemplateResponse("settings.html", context, status_code=422)


@app.post("/settings/lock-term")
def lock_term(
    request: Request,
    year: int = Form(...),
    term: int = Form(...),
) -> RedirectResponse:
    require_admin(request)
    actor = current_actor(request)
    ledger.lock_term(year=year, term_index=term, actor=actor)
    LOGGER.info("Termin last year=%s term=%s by=%s", year, term, actor)
    return RedirectResponse(f"/settings?year={year}", status_code=303)


@app.post("/settings/run-legacy-migration")
def run_legacy_migration(request: Request) -> RedirectResponse:
    require_admin(request)
    actor = current_actor(request)
    result = migrate_legacy.run_legacy_migration(actor=actor)
    LOGGER.info(
        "Legacy-migrering utfort av=%s incomes_migrert=%s expenses_migrert=%s",
        actor,
        result["incomes"]["migrated"],
        result["expenses"]["migrated"],
    )
    return RedirectResponse("/settings", status_code=303)


@app.get("/settings/import-legacy", response_class=HTMLResponse)
def import_legacy_page(request: Request) -> HTMLResponse:
    require_admin(request)
    context = legacy_import_page_context(request)
    return templates.TemplateResponse("legacy_import.html", context)


@app.post("/settings/import-legacy/preview", response_class=HTMLResponse)
async def import_legacy_preview(
    request: Request,
    db_path: str = Form(""),
    upload_db: UploadFile | None = File(default=None),
    import_settings: str = Form("0"),
) -> HTMLResponse:
    require_admin(request)

    errors: list[str] = []
    selected_path: Path | None = None
    if upload_db and upload_db.filename:
        try:
            selected_path = await save_legacy_upload(upload_db)
        except HTTPException as exc:
            errors.append(str(exc.detail))
    elif db_path.strip():
        selected_path = Path(db_path.strip()).expanduser()
    else:
        errors.append("Oppgi sti til DB-fil eller last opp en legacy-DB.")

    preview: dict | None = None
    if selected_path is not None:
        preview = legacy_import.preview_legacy_database(selected_path)
        if not preview["valid"]:
            errors.extend(preview["errors"])

    form_data = {
        "db_path": db_path.strip(),
        "source_path": str(selected_path.resolve()) if selected_path else "",
        "import_settings": "1" if import_settings == "1" else "0",
    }
    context = legacy_import_page_context(request, form_data=form_data, preview=preview, errors=errors)
    status = 422 if errors else 200
    return templates.TemplateResponse("legacy_import.html", context, status_code=status)


@app.post("/settings/import-legacy/confirm", response_class=HTMLResponse)
def import_legacy_confirm(
    request: Request,
    source_path: str = Form(...),
    import_settings: str = Form("0"),
    confirm_import: str = Form("0"),
) -> HTMLResponse:
    require_admin(request)
    errors: list[str] = []
    actor = current_actor(request)
    source = source_path.strip()
    preview = legacy_import.preview_legacy_database(source) if source else None
    if not source:
        errors.append("Kilde-sti mangler.")
    if confirm_import != "1":
        errors.append("Du må bekrefte import før kjøring.")
    if preview and not preview["valid"]:
        errors.extend(preview["errors"])
    if preview and preview.get("is_current_db"):
        errors.append("Valgt fil er aktiv database. Velg en separat legacy-fil for import.")

    form_data = {
        "db_path": source,
        "source_path": source,
        "import_settings": "1" if import_settings == "1" else "0",
    }
    if errors:
        context = legacy_import_page_context(request, form_data=form_data, preview=preview, errors=errors)
        return templates.TemplateResponse("legacy_import.html", context, status_code=422)

    try:
        result = legacy_import.import_legacy_database(
            source_path=source,
            actor=actor,
            import_settings=import_settings == "1",
        )
        LOGGER.info("Legacy-import fullfort av=%s import_settings=%s", actor, import_settings == "1")
        success_message = "Legacy-data ble importert og migrert trygt. Opprinnelig database er sikkerhetskopiert."
        context = legacy_import_page_context(
            request,
            form_data=form_data,
            preview=preview,
            import_result=result,
            success_message=success_message,
        )
        return templates.TemplateResponse("legacy_import.html", context)
    except Exception as exc:
        errors.append(str(exc))
        context = legacy_import_page_context(request, form_data=form_data, preview=preview, errors=errors)
        return templates.TemplateResponse("legacy_import.html", context, status_code=422)


@app.get("/attachments/{kind}/{item_id}")
def get_legacy_attachment(kind: str, item_id: int) -> FileResponse:
    if kind == "income":
        row = crud.get_income(item_id)
    elif kind == "expense":
        row = crud.get_expense(item_id)
    else:
        raise HTTPException(status_code=400, detail="Ugyldig vedleggstype")

    if row is None or not row.get("attachment_stored_name"):
        raise HTTPException(status_code=404, detail="Vedlegg ikke funnet")

    file_path = db.ATTACHMENTS_DIR / row["attachment_stored_name"]
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Vedlegg mangler pa disk")

    return FileResponse(
        path=file_path,
        filename=row.get("attachment_original_name") or row["attachment_stored_name"],
        media_type="application/octet-stream",
    )


@app.get("/bilag/{bilag_id}")
def get_bilag(bilag_id: int) -> FileResponse:
    conn = db.get_connection()
    try:
        row = conn.execute("SELECT * FROM bilag_files WHERE id = ?", (bilag_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Bilag ikke funnet")

    file_path = db.ATTACHMENTS_DIR / row["stored_name"]
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Bilag mangler pa disk")
    return FileResponse(
        path=file_path,
        filename=row["original_name"],
        media_type=row["mime_type"] or "application/octet-stream",
    )
