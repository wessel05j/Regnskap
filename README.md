# Mini-regnskap for ENK (Wessel Media)

Lokal webapp for enkeltpersonforetak (ENK) med fokus pa intern kontroll av inntekter, utgifter, MVA-oppfolging og PDF-rapporter.  
Dette er **ikke** en offisiell innsendingstjeneste mot Altinn.

## Teknologi

- Python 3.11+
- FastAPI
- SQLite (`data/app.db`)
- Jinja2 templates + enkel CSS
- ReportLab for PDF

## Sikkerhet og data

- Regnskapsdata lagres lokalt i `data/`.
- `data/`, vedlegg, rapporter, `.db` og loggfiler er ignorert i `.gitignore`.
- Ingen hemmeligheter er hardkodet i repoet.
- Ingen Altinn-integrasjon eller signering.

## Prosjektstruktur

```text
app/
  main.py
  db.py
  models.py
  schemas.py
  crud.py
  pdf_reports.py
  seed_demo.py
  templates/
  static/
scripts/
  start.bat
  start.ps1
tests/
requirements.txt
```

## Oppstart pa Windows

1. Installer Python 3.11 eller nyere.
2. Dobbelklikk `scripts/start.bat`.
3. Scriptet oppretter `.venv` ved behov, installerer avhengigheter ved behov, starter server og apner:
   - `http://127.0.0.1:8000`

Alternativt i PowerShell:

```powershell
.\scripts\start.ps1
```

## Bruk

1. Gaa til `Dashboard` for oversikt over arets summer og siste transaksjoner.
2. Legg inn inntekter via `Inntekter -> Ny inntekt`.
3. Legg inn utgifter via `Utgifter -> Ny utgift`.
4. Last opp vedlegg (PDF/JPG/PNG), maks 10MB.
5. Sett firmaopplysninger i `Settings`.
   - Inkluder standard utgaende MVA-sats (typisk 0% for eksporttjenester).
6. Generer rapporter i `Rapporter`:
   - Arsoversikt (PDF)
   - MVA-terminrapport (PDF)

## Valuta og NOK-beregning

- Originalt belop + valuta lagres alltid.
- Du kan gi:
  - `Belop i NOK` manuelt, eller
  - `Valutakurs` manuelt.
- Hvis ingen NOK-beregning finnes og valuta ikke er NOK, markeres transaksjonen som "mangler NOK".
- NOK-summer i dashboard/rapporter bruker kun transaksjoner med tilgjengelig NOK-belop.

## Demo-data (valgfritt)

Kjor:

```powershell
python -m app.seed_demo
```

Dette legger inn eksempeltransaksjoner.

## Tester

Kjor enhetstester med:

```powershell
pytest
```

Testdekning i dette repoet inkluderer:
- valutakonvertering
- arsummering
- terminsummering
- filnavn-sanitization
- CRUD create/read

## Viktig disklaimer

- Systemet er for intern administrasjon.
- PDF-ene er til kontroll og dokumentasjon, ikke offisiell innsending.
