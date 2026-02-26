# Mini-regnskap for ENK

Lokal FastAPI-app for ENK med bilagsføring (double-entry), MVA-spesifikasjon, term-lås, korreksjonsflyt, rapporter og lokal innlogging.

## Teknologi

- Python 3.11+
- FastAPI + Jinja2
- SQLite (`data/app.db`)
- ReportLab (PDF)
- Pytest

## Oppstart

```powershell
.\scripts\start.ps1
```

eller:

```bat
scripts\start.bat
```

## Kom i gang (kortversjon)

1. Åpne `http://127.0.0.1:8000/bootstrap-admin`.
2. Opprett første adminbruker og logg inn.
3. Gå til `Innstillinger` og fyll inn firmaopplysninger.
4. Opprett bilag i `Bilag -> Nytt bilag`.
5. Legg ved bilag (PDF/JPG/PNG) ved behov.
6. Kjør rapporter i `Rapporter`.
7. Lås termin i `Innstillinger` når perioden er ferdig avstemt.
8. Rett feil via `Bilag -> Opprett korreksjon` (reversering + nytt korrigert bilag).

## Eksempelbilag

### YouTube-inntekt (enkelt eksempel)

- Debet `1920 Bank`
- Kredit `3100 Salgsinntekt avgiftsfri` (eller `3000` + MVA-felt ved avgiftspliktig salg)

### PC-kjøp med MVA (eksempel)

- Debet kostnadskonto (f.eks. `4000/5000`) for netto
- Debet `2720 Inngående MVA`
- Kredit `1920 Bank` for totalbeløp

## Læringsinnhold i appen

- `Lær`-meny med begrepsliste på bokmål.
- `Kom i gang (ENK)`-side i appen.
- Tooltip (`?`) ved avanserte felter i skjemaer og rapporter.

## Legacy-data og import

### Når data allerede ligger i aktiv DB

Bruk `Innstillinger -> Kjør legacy-migrering`.

### Når data ligger i separat gammel DB-fil

Bruk `Innstillinger -> Importer gammel database`.

Flyten gjør:

1. Schema-validering (`settings`, `incomes`, `expenses`).
2. Forhåndsvisning av antall rader.
3. Eksplisitt bekreftelse før import.
4. Trygg kjøring via staging-kopi + backup før bytte.

## Rapporter

- Årsrapport: `/reports/yearly`
- MVA (PDF/JSON/CSV): `/reports/mva`, `/reports/mva/json`, `/reports/mva/csv`
- Journal (PDF/CSV): `/reports/journal/pdf`, `/reports/journal/csv`
- Kontospesifikasjon (PDF/CSV): `/reports/accounts/pdf`, `/reports/accounts/csv`

## Test

```powershell
$env:PYTHONPATH='.'
pytest -q
```

## Skjermbilder (plassholdere)

- `[Skjermbildeplassholder] Oversikt` -> `docs/screenshots/oversikt.png`
- `[Skjermbildeplassholder] Bilagsskjema` -> `docs/screenshots/bilag_form.png`
- `[Skjermbildeplassholder] Rapporter (MVA/Konto)` -> `docs/screenshots/rapporter.png`
- `[Skjermbildeplassholder] Lær / Kom i gang` -> `docs/screenshots/laer.png`
- `[Skjermbildeplassholder] Legacy-import` -> `docs/screenshots/legacy_import.png`
