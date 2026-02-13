from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app import crud, db, pdf_reports, schemas
from app.utils import MAX_ATTACHMENT_SIZE, TERM_RANGES, parse_float, sanitize_filename

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="Mini Regnskap ENK")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

LOGGER = logging.getLogger("regnskap")


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
    db.init_db()
    LOGGER.info("Systemet startet")


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


def base_context(request: Request, active_nav: str) -> dict:
    return {
        "request": request,
        "active_nav": active_nav,
        "settings": crud.get_settings(),
        "disclaimer": "Dette er intern oversikt og ikke offisiell innsending.",
    }


async def save_attachment(upload: UploadFile | None) -> tuple[str | None, str | None]:
    if upload is None or not upload.filename:
        return None, None

    payload = await upload.read()
    if len(payload) > MAX_ATTACHMENT_SIZE:
        raise HTTPException(status_code=400, detail="Vedlegg overstiger 10MB grense")

    original_name = sanitize_filename(upload.filename)
    suffix = Path(original_name).suffix
    allowed_suffixes = {".pdf", ".jpg", ".jpeg", ".png"}
    if suffix.lower() not in allowed_suffixes:
        raise HTTPException(status_code=400, detail="Ugyldig filtype. Tillatt: PDF, JPG, JPEG, PNG")
    stored_name = f"{uuid4().hex}{suffix.lower()}"
    file_path = db.ATTACHMENTS_DIR / stored_name
    file_path.write_bytes(payload)
    return stored_name, original_name


def remove_attachment(stored_name: str | None) -> None:
    if not stored_name:
        return
    file_path = db.ATTACHMENTS_DIR / stored_name
    if file_path.exists():
        file_path.unlink(missing_ok=True)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, year: str | None = None) -> HTMLResponse:
    selected_year = crud.parse_year(year)
    summary = crud.get_dashboard_summary(selected_year)
    latest = crud.list_latest_transactions(10)
    context = base_context(request, active_nav="dashboard")
    context.update(
        {
            "selected_year": selected_year,
            "years": crud.available_years(),
            "summary": summary,
            "latest_transactions": latest,
        }
    )
    return templates.TemplateResponse("dashboard.html", context)


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
            "filters": {"start_date": start_date or "", "end_date": end_date or "", "q": q or ""},
        }
    )
    return templates.TemplateResponse("incomes_list.html", context)


@app.get("/incomes/new", response_class=HTMLResponse)
def income_new(request: Request) -> HTMLResponse:
    context = base_context(request, active_nav="incomes")
    context.update(
        {
            "mode": "create",
            "form_data": {
                "date": today_iso(),
                "amount_original": "",
                "currency": "NOK",
                "amount_nok": "",
                "exchange_rate": "",
                "source": "YouTube/Google AdSense",
                "note": "",
            },
            "errors": {},
            "currencies": enum_values(schemas.Currency),
            "income": None,
        }
    )
    return templates.TemplateResponse("income_form.html", context)


@app.post("/incomes/new", response_class=HTMLResponse)
async def income_create(
    request: Request,
    date_value: str = Form(alias="date"),
    amount_original: str = Form(...),
    currency: str = Form(...),
    amount_nok: str = Form(""),
    exchange_rate: str = Form(""),
    source: str = Form(...),
    note: str = Form(""),
    attachment: UploadFile | None = File(default=None),
) -> HTMLResponse:
    data = {
        "date": date_value,
        "amount_original": parse_float(amount_original),
        "currency": currency,
        "amount_nok": parse_float(amount_nok),
        "exchange_rate": parse_float(exchange_rate),
        "source": source,
        "note": note,
    }

    try:
        payload = schemas.IncomeInput.model_validate(data)
        stored_name, original_name = await save_attachment(attachment)
        crud.create_income(payload, stored_name, original_name)
        LOGGER.info("Ny inntekt registrert")
        return RedirectResponse("/incomes", status_code=303)
    except ValidationError as exc:
        context = base_context(request, active_nav="incomes")
        context.update(
            {
                "mode": "create",
                "form_data": {
                    "date": date_value,
                    "amount_original": amount_original,
                    "currency": currency,
                    "amount_nok": amount_nok,
                    "exchange_rate": exchange_rate,
                    "source": source,
                    "note": note,
                },
                "errors": form_errors(exc),
                "currencies": enum_values(schemas.Currency),
                "income": None,
            }
        )
        return templates.TemplateResponse("income_form.html", context, status_code=422)


@app.get("/incomes/{income_id}/edit", response_class=HTMLResponse)
def income_edit(request: Request, income_id: int) -> HTMLResponse:
    income = crud.get_income(income_id)
    if income is None:
        raise HTTPException(status_code=404, detail="Inntekt ikke funnet")

    context = base_context(request, active_nav="incomes")
    context.update(
        {
            "mode": "edit",
            "form_data": {
                "date": income["date"],
                "amount_original": income["amount_original"],
                "currency": income["currency"],
                "amount_nok": income["amount_nok"] if income["amount_nok"] is not None else "",
                "exchange_rate": income["exchange_rate"] if income["exchange_rate"] is not None else "",
                "source": income["source"],
                "note": income["note"] or "",
            },
            "errors": {},
            "currencies": enum_values(schemas.Currency),
            "income": income,
        }
    )
    return templates.TemplateResponse("income_form.html", context)


@app.post("/incomes/{income_id}/edit", response_class=HTMLResponse)
async def income_update(
    request: Request,
    income_id: int,
    date_value: str = Form(alias="date"),
    amount_original: str = Form(...),
    currency: str = Form(...),
    amount_nok: str = Form(""),
    exchange_rate: str = Form(""),
    source: str = Form(...),
    note: str = Form(""),
    attachment: UploadFile | None = File(default=None),
) -> HTMLResponse:
    income = crud.get_income(income_id)
    if income is None:
        raise HTTPException(status_code=404, detail="Inntekt ikke funnet")

    data = {
        "date": date_value,
        "amount_original": parse_float(amount_original),
        "currency": currency,
        "amount_nok": parse_float(amount_nok),
        "exchange_rate": parse_float(exchange_rate),
        "source": source,
        "note": note,
    }

    try:
        payload = schemas.IncomeInput.model_validate(data)
        new_stored, new_original = await save_attachment(attachment)
        keep_existing = new_stored is None
        if not keep_existing:
            remove_attachment(income["attachment_stored_name"])
        crud.update_income(
            income_id=income_id,
            payload=payload,
            attachment_stored_name=new_stored,
            attachment_original_name=new_original,
            keep_existing_attachment=keep_existing,
        )
        LOGGER.info("Inntekt oppdatert id=%s", income_id)
        return RedirectResponse("/incomes", status_code=303)
    except ValidationError as exc:
        context = base_context(request, active_nav="incomes")
        context.update(
            {
                "mode": "edit",
                "form_data": {
                    "date": date_value,
                    "amount_original": amount_original,
                    "currency": currency,
                    "amount_nok": amount_nok,
                    "exchange_rate": exchange_rate,
                    "source": source,
                    "note": note,
                },
                "errors": form_errors(exc),
                "currencies": enum_values(schemas.Currency),
                "income": income,
            }
        )
        return templates.TemplateResponse("income_form.html", context, status_code=422)


@app.post("/incomes/{income_id}/delete")
def income_delete(income_id: int) -> RedirectResponse:
    income = crud.get_income(income_id)
    if income:
        remove_attachment(income["attachment_stored_name"])
    crud.delete_income(income_id)
    LOGGER.info("Inntekt slettet id=%s", income_id)
    return RedirectResponse("/incomes", status_code=303)


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


@app.get("/expenses/new", response_class=HTMLResponse)
def expense_new(request: Request) -> HTMLResponse:
    context = base_context(request, active_nav="expenses")
    context.update(
        {
            "mode": "create",
            "form_data": {
                "date": today_iso(),
                "vendor": "",
                "category": schemas.ExpenseCategory.OTHER.value,
                "amount_original": "",
                "currency": "NOK",
                "amount_nok": "",
                "exchange_rate": "",
                "vat_amount": "",
                "payment_method": schemas.PaymentMethod.CARD.value,
                "note": "",
            },
            "errors": {},
            "currencies": enum_values(schemas.Currency),
            "categories": enum_values(schemas.ExpenseCategory),
            "payment_methods": enum_values(schemas.PaymentMethod),
            "expense": None,
        }
    )
    return templates.TemplateResponse("expense_form.html", context)


@app.post("/expenses/new", response_class=HTMLResponse)
async def expense_create(
    request: Request,
    date_value: str = Form(alias="date"),
    vendor: str = Form(...),
    category: str = Form(...),
    amount_original: str = Form(...),
    currency: str = Form(...),
    amount_nok: str = Form(""),
    exchange_rate: str = Form(""),
    vat_amount: str = Form(""),
    payment_method: str = Form(...),
    note: str = Form(""),
    attachment: UploadFile | None = File(default=None),
) -> HTMLResponse:
    data = {
        "date": date_value,
        "vendor": vendor,
        "category": category,
        "amount_original": parse_float(amount_original),
        "currency": currency,
        "amount_nok": parse_float(amount_nok),
        "exchange_rate": parse_float(exchange_rate),
        "vat_amount": parse_float(vat_amount),
        "payment_method": payment_method,
        "note": note,
    }

    try:
        payload = schemas.ExpenseInput.model_validate(data)
        stored_name, original_name = await save_attachment(attachment)
        crud.create_expense(payload, stored_name, original_name)
        LOGGER.info("Ny utgift registrert")
        return RedirectResponse("/expenses", status_code=303)
    except ValidationError as exc:
        context = base_context(request, active_nav="expenses")
        context.update(
            {
                "mode": "create",
                "form_data": {
                    "date": date_value,
                    "vendor": vendor,
                    "category": category,
                    "amount_original": amount_original,
                    "currency": currency,
                    "amount_nok": amount_nok,
                    "exchange_rate": exchange_rate,
                    "vat_amount": vat_amount,
                    "payment_method": payment_method,
                    "note": note,
                },
                "errors": form_errors(exc),
                "currencies": enum_values(schemas.Currency),
                "categories": enum_values(schemas.ExpenseCategory),
                "payment_methods": enum_values(schemas.PaymentMethod),
                "expense": None,
            }
        )
        return templates.TemplateResponse("expense_form.html", context, status_code=422)


@app.get("/expenses/{expense_id}/edit", response_class=HTMLResponse)
def expense_edit(request: Request, expense_id: int) -> HTMLResponse:
    expense = crud.get_expense(expense_id)
    if expense is None:
        raise HTTPException(status_code=404, detail="Utgift ikke funnet")

    context = base_context(request, active_nav="expenses")
    context.update(
        {
            "mode": "edit",
            "form_data": {
                "date": expense["date"],
                "vendor": expense["vendor"],
                "category": expense["category"],
                "amount_original": expense["amount_original"],
                "currency": expense["currency"],
                "amount_nok": expense["amount_nok"] if expense["amount_nok"] is not None else "",
                "exchange_rate": expense["exchange_rate"] if expense["exchange_rate"] is not None else "",
                "vat_amount": expense["vat_amount"] if expense["vat_amount"] is not None else "",
                "payment_method": expense["payment_method"],
                "note": expense["note"] or "",
            },
            "errors": {},
            "currencies": enum_values(schemas.Currency),
            "categories": enum_values(schemas.ExpenseCategory),
            "payment_methods": enum_values(schemas.PaymentMethod),
            "expense": expense,
        }
    )
    return templates.TemplateResponse("expense_form.html", context)


@app.post("/expenses/{expense_id}/edit", response_class=HTMLResponse)
async def expense_update(
    request: Request,
    expense_id: int,
    date_value: str = Form(alias="date"),
    vendor: str = Form(...),
    category: str = Form(...),
    amount_original: str = Form(...),
    currency: str = Form(...),
    amount_nok: str = Form(""),
    exchange_rate: str = Form(""),
    vat_amount: str = Form(""),
    payment_method: str = Form(...),
    note: str = Form(""),
    attachment: UploadFile | None = File(default=None),
) -> HTMLResponse:
    expense = crud.get_expense(expense_id)
    if expense is None:
        raise HTTPException(status_code=404, detail="Utgift ikke funnet")

    data = {
        "date": date_value,
        "vendor": vendor,
        "category": category,
        "amount_original": parse_float(amount_original),
        "currency": currency,
        "amount_nok": parse_float(amount_nok),
        "exchange_rate": parse_float(exchange_rate),
        "vat_amount": parse_float(vat_amount),
        "payment_method": payment_method,
        "note": note,
    }

    try:
        payload = schemas.ExpenseInput.model_validate(data)
        new_stored, new_original = await save_attachment(attachment)
        keep_existing = new_stored is None
        if not keep_existing:
            remove_attachment(expense["attachment_stored_name"])
        crud.update_expense(
            expense_id=expense_id,
            payload=payload,
            attachment_stored_name=new_stored,
            attachment_original_name=new_original,
            keep_existing_attachment=keep_existing,
        )
        LOGGER.info("Utgift oppdatert id=%s", expense_id)
        return RedirectResponse("/expenses", status_code=303)
    except ValidationError as exc:
        context = base_context(request, active_nav="expenses")
        context.update(
            {
                "mode": "edit",
                "form_data": {
                    "date": date_value,
                    "vendor": vendor,
                    "category": category,
                    "amount_original": amount_original,
                    "currency": currency,
                    "amount_nok": amount_nok,
                    "exchange_rate": exchange_rate,
                    "vat_amount": vat_amount,
                    "payment_method": payment_method,
                    "note": note,
                },
                "errors": form_errors(exc),
                "currencies": enum_values(schemas.Currency),
                "categories": enum_values(schemas.ExpenseCategory),
                "payment_methods": enum_values(schemas.PaymentMethod),
                "expense": expense,
            }
        )
        return templates.TemplateResponse("expense_form.html", context, status_code=422)


@app.post("/expenses/{expense_id}/delete")
def expense_delete(expense_id: int) -> RedirectResponse:
    expense = crud.get_expense(expense_id)
    if expense:
        remove_attachment(expense["attachment_stored_name"])
    crud.delete_expense(expense_id)
    LOGGER.info("Utgift slettet id=%s", expense_id)
    return RedirectResponse("/expenses", status_code=303)


@app.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request, year: str | None = None, term: str | None = None) -> HTMLResponse:
    selected_year = crud.parse_year(year)
    selected_term = crud.parse_term(term)
    settings = crud.get_settings()
    output_rate = float(settings.get("default_output_vat_rate") or 0.0)
    year_data = crud.yearly_report_data(selected_year)
    term_data = crud.term_report_data(selected_year, selected_term, outgoing_vat_rate_percent=output_rate)

    context = base_context(request, active_nav="reports")
    context.update(
        {
            "years": crud.available_years(),
            "selected_year": selected_year,
            "selected_term": selected_term,
            "terms": list(enumerate(TERM_RANGES, start=1)),
            "year_data": year_data,
            "term_data": term_data,
            "output_rate": output_rate,
        }
    )
    return templates.TemplateResponse("reports.html", context)


@app.post("/reports/yearly")
def reports_yearly(year: int = Form(...)) -> FileResponse:
    settings = crud.get_settings()
    data = crud.yearly_report_data(year)
    output = pdf_reports.yearly_report_output_path(year, crud.format_now_for_filename())
    pdf_reports.generate_yearly_report_pdf(data, settings, output)
    LOGGER.info("Arsrapport generert for ar=%s", year)
    return FileResponse(path=output, filename=output.name, media_type="application/pdf")


@app.post("/reports/mva")
def reports_term(
    year: int = Form(...),
    term: int = Form(...),
) -> FileResponse:
    settings = crud.get_settings()
    output_rate = float(settings.get("default_output_vat_rate") or 0.0)
    data = crud.term_report_data(year=year, term_index=term, outgoing_vat_rate_percent=output_rate)
    output = pdf_reports.term_report_output_path(year, term, crud.format_now_for_filename())
    pdf_reports.generate_term_report_pdf(data, settings, output)
    LOGGER.info("MVA-rapport generert for ar=%s termin=%s", year, term)
    return FileResponse(path=output, filename=output.name, media_type="application/pdf")


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request) -> HTMLResponse:
    current = crud.get_settings()
    context = base_context(request, active_nav="settings")
    context.update(
        {
            "form_data": current,
            "errors": {},
            "currencies": enum_values(schemas.Currency),
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
        context = base_context(request, active_nav="settings")
        context.update(
            {
                "form_data": input_data,
                "errors": form_errors(exc),
                "currencies": enum_values(schemas.Currency),
            }
        )
        return templates.TemplateResponse("settings.html", context, status_code=422)


@app.get("/attachments/{kind}/{item_id}")
def get_attachment(kind: str, item_id: int) -> FileResponse:
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
