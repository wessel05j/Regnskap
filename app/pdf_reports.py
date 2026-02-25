from __future__ import annotations

from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app import db


def _new_canvas(path: Path) -> canvas.Canvas:
    path.parent.mkdir(parents=True, exist_ok=True)
    return canvas.Canvas(str(path), pagesize=A4)


def generate_yearly_report_pdf(data: dict[str, Any], settings: dict[str, Any], output_path: Path) -> Path:
    c = _new_canvas(output_path)
    width, height = A4
    y = height - 40

    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, y, f"{settings['company_name']} - Arsoversikt {data['year']}")
    y -= 18
    c.setFont("Helvetica", 10)
    c.drawString(40, y, f"Org.nr: {settings.get('org_number') or '-'}")
    y -= 16
    c.drawString(40, y, "Dette er intern oversikt og ikke offisiell innsending.")
    y -= 22

    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "Summer (NOK)")
    y -= 16
    c.setFont("Helvetica", 10)
    c.drawString(40, y, f"Inntekter: {data['income_total_nok']:.2f}")
    y -= 14
    c.drawString(40, y, f"Utgifter: {data['expense_total_nok']:.2f}")
    y -= 14
    c.drawString(40, y, f"Resultat: {data['result_nok']:.2f}")
    y -= 14
    c.drawString(40, y, f"Mangler NOK-omregning: {data['missing_nok_count']}")
    y -= 20

    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "Fordeling per utgiftskategori (NOK)")
    y -= 14
    c.setFont("Helvetica", 10)
    if data["category_totals"]:
        for category, amount in sorted(data["category_totals"].items()):
            c.drawString(50, y, f"{category}: {amount:.2f}")
            y -= 12
            if y < 80:
                c.showPage()
                y = height - 40
                c.setFont("Helvetica", 10)
    else:
        c.drawString(50, y, "Ingen registrerte utgifter.")
        y -= 14

    y -= 8
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "Vouchers")
    y -= 14
    c.setFont("Helvetica", 9)
    for tx in data["transactions"]:
        amount_text = f"{tx['amount_nok']:.2f} NOK"
        line = f"{tx['date']} | {tx['type']} | {tx['label']} | {amount_text}"
        c.drawString(40, y, line[:115])
        y -= 11
        if y < 40:
            c.showPage()
            y = height - 40
            c.setFont("Helvetica", 9)

    c.showPage()
    c.save()
    return output_path


def generate_term_report_pdf(data: dict[str, Any], settings: dict[str, Any], output_path: Path) -> Path:
    c = _new_canvas(output_path)
    width, height = A4
    y = height - 40

    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, y, f"{settings['company_name']} - MVA terminrapport {data['term_label']} {data['year']}")
    y -= 18
    c.setFont("Helvetica", 10)
    c.drawString(40, y, f"Org.nr: {settings.get('org_number') or '-'}")
    y -= 16
    c.drawString(40, y, f"Periode: {data['start_date']} til {data['end_date']}")
    y -= 16
    c.drawString(40, y, "Belop i rapporten er hele NOK.")
    y -= 22

    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "MVA-spesifikasjon per mvaKode")
    y -= 16
    c.setFont("Helvetica", 10)
    c.drawString(40, y, "mvaKode | Sats | Grunnlag (NOK) | MVA (NOK)")
    y -= 12
    c.drawString(40, y, "-" * 80)
    y -= 12

    for line in data["lines"]:
        sats_text = "-" if line["sats"] is None else f"{line['sats'] * 100:.2f}%"
        text = f"{line['mvaKode']} | {sats_text} | {int(line['grunnlag_nok'])} | {int(line['merverdiavgift_nok'])}"
        c.drawString(40, y, text[:115])
        y -= 12
        if y < 80:
            c.showPage()
            y = height - 40
            c.setFont("Helvetica", 10)

    y -= 6
    c.drawString(40, y, f"Totalt grunnlag: {int(data['totals']['grunnlag_nok'])} NOK")
    y -= 14
    c.drawString(40, y, f"Total MVA: {int(data['totals']['merverdiavgift_nok'])} NOK")
    y -= 14
    c.drawString(40, y, f"Valideringsfeil: {len(data['validation_errors'])}")

    c.showPage()
    y = height - 40
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "Drilldown per mvaKode")
    y -= 16
    c.setFont("Helvetica", 9)
    for line in data["lines"]:
        c.setFont("Helvetica-Bold", 10)
        sats_text = "-" if line["sats"] is None else f"{line['sats'] * 100:.2f}%"
        c.drawString(
            40,
            y,
            f"Kode {line['mvaKode']} | sats {sats_text} | grunnlag {int(line['grunnlag_nok'])} | mva {int(line['merverdiavgift_nok'])}",
        )
        y -= 12
        c.setFont("Helvetica", 9)
        for dr in line["drilldown"]:
            bilag_text = f" bilag:{dr['bilag']['original_name']}" if dr["bilag"] else ""
            text = (
                f"{dr['posting_date']} {dr['voucher_ref']} L{dr['voucher_line_no']} {dr.get('counterparty_name') or '-'}"
                f" grunnlag={int(dr['grunnlag_nok'])} mva={int(dr['merverdiavgift_nok'])}{bilag_text}"
            )
            c.drawString(45, y, text[:120])
            y -= 11
            if y < 40:
                c.showPage()
                y = height - 40
                c.setFont("Helvetica", 9)
        y -= 4
        if y < 40:
            c.showPage()
            y = height - 40
            c.setFont("Helvetica", 9)

    c.showPage()
    c.save()
    return output_path


def generate_journal_pdf(
    rows: list[dict[str, Any]],
    settings: dict[str, Any],
    output_path: Path,
    *,
    start_date: str,
    end_date: str,
) -> Path:
    c = _new_canvas(output_path)
    width, height = A4
    y = height - 40
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, y, f"{settings['company_name']} - Bokforingsspesifikasjon")
    y -= 16
    c.setFont("Helvetica", 10)
    c.drawString(40, y, f"Periode: {start_date} til {end_date}")
    y -= 16
    c.setFont("Helvetica", 9)
    for row in rows:
        text = (
            f"{row['posting_date']} {row['voucher_series']}-{row['voucher_no']} L{row['line_no']} "
            f"{row['account_no']} {row['account_name']} D:{row['debit_nok']} K:{row['credit_nok']} "
            f"{row['line_description'] or ''}"
        )
        c.drawString(40, y, text[:120])
        y -= 11
        if y < 40:
            c.showPage()
            y = height - 40
            c.setFont("Helvetica", 9)
    c.showPage()
    c.save()
    return output_path


def generate_account_spec_pdf(
    rows: list[dict[str, Any]],
    settings: dict[str, Any],
    output_path: Path,
    *,
    start_date: str,
    end_date: str,
    account_no: str | None,
) -> Path:
    c = _new_canvas(output_path)
    width, height = A4
    y = height - 40
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, y, f"{settings['company_name']} - Kontospesifikasjon")
    y -= 16
    c.setFont("Helvetica", 10)
    c.drawString(40, y, f"Periode: {start_date} til {end_date}")
    y -= 14
    c.drawString(40, y, f"Konto-filter: {account_no or 'alle'}")
    y -= 16
    c.setFont("Helvetica", 9)
    for row in rows:
        text = (
            f"{row['account_no']} {row['account_name']} | {row['posting_date']} {row['voucher_series']}-{row['voucher_no']} "
            f"D:{row['debit_nok']} K:{row['credit_nok']} Saldo:{row['running_balance_nok']}"
        )
        c.drawString(40, y, text[:120])
        y -= 11
        if y < 40:
            c.showPage()
            y = height - 40
            c.setFont("Helvetica", 9)
    c.showPage()
    c.save()
    return output_path


def yearly_report_output_path(year: int, timestamp: str) -> Path:
    return db.REPORTS_DIR / f"arsoversikt_{year}_{timestamp}.pdf"


def term_report_output_path(year: int, term_index: int, timestamp: str) -> Path:
    return db.REPORTS_DIR / f"mva_termin_{year}_{term_index}_{timestamp}.pdf"


def journal_report_output_path(start_date: str, end_date: str, timestamp: str) -> Path:
    return db.REPORTS_DIR / f"bokforing_{start_date}_{end_date}_{timestamp}.pdf"


def account_report_output_path(start_date: str, end_date: str, timestamp: str) -> Path:
    return db.REPORTS_DIR / f"kontospes_{start_date}_{end_date}_{timestamp}.pdf"
