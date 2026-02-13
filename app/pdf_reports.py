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
        c.drawString(50, y, "Ingen registrerte utgifter med NOK-belop.")
        y -= 14

    y -= 8
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "Transaksjoner")
    y -= 14
    c.setFont("Helvetica", 9)
    for tx in data["transactions"]:
        amount_text = f"{tx['amount_nok']:.2f} NOK" if tx["amount_nok"] is not None else f"{tx['amount_original']:.2f} {tx['currency']} (mangler NOK)"
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
    c.drawString(40, y, "Dette er intern oversikt og ikke offisiell innsending.")
    y -= 22

    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "MVA-oversikt")
    y -= 16
    c.setFont("Helvetica", 10)
    c.drawString(40, y, f"Omsetning (NOK): {data['turnover_nok']:.2f}")
    y -= 14
    c.drawString(40, y, f"Utgaende MVA-sats: {data['output_vat_rate_percent']:.2f}%")
    y -= 14
    c.drawString(40, y, f"Utgaende MVA (NOK): {data['output_vat']:.2f}")
    y -= 14
    c.drawString(40, y, f"Inngaende MVA (NOK): {data['input_vat']:.2f}")
    y -= 14
    c.drawString(40, y, f"Netto (Inngaende - Utgaende): {data['net_vat_input_minus_output']:.2f}")
    y -= 14
    c.drawString(40, y, f"Netto (Utgaende - Inngaende): {data['net_vat_output_minus_input']:.2f}")
    y -= 20

    c.drawString(40, y, "Notat: For eksport av digitale tjenester er utgaende MVA ofte 0%.")
    y -= 14
    c.drawString(40, y, "Ingen innsending til Altinn skjer fra dette systemet.")

    c.showPage()
    c.save()
    return output_path


def yearly_report_output_path(year: int, timestamp: str) -> Path:
    return db.REPORTS_DIR / f"arsoversikt_{year}_{timestamp}.pdf"


def term_report_output_path(year: int, term_index: int, timestamp: str) -> Path:
    return db.REPORTS_DIR / f"mva_termin_{year}_{term_index}_{timestamp}.pdf"
