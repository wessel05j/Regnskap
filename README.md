# Mini-regnskap for ENK (Wessel Media)

Lokal FastAPI-app for ENK med voucher-basert bokforing (double-entry), MVA-spesifikasjon per `mvaKode`, periodelaas, audit-logg, PDF/CSV/JSON-rapporter, enkel admin-login og backup CLI.

Dette er fortsatt et internt system og **ikke** en direkte innsendingstjeneste mot Altinn.

## Teknologi

- Python 3.11+
- FastAPI + Jinja2
- SQLite (`data/app.db`)
- ReportLab (PDF)
- Pytest

## Ny datamodell (kjerne)

I tillegg til legacy-tabeller (`incomes`, `expenses`) er disse lagt til:

- `accounts`: kontoplan
- `fiscal_periods`: perioder/terminer med laasestatus
- `vouchers`: bilagshode/voucher med sekvensnummer
- `voucher_lines`: voucherlinjer (debet/kredit + MVA-felter)
- `bilag_files`: vedleggsregister med hash (`sha256`)
- `audit_log`: kontrollspor (hvem/hva/nar)
- `users`, `user_sessions`: lokal autentisering/sesjoner
- `voucher_sequences`: sekvenskontroll for voucher_no
- `schema_migrations`: versjonert migreringshistorikk

Legacy-tabeller beholdes og vises som read-only i UI.

## Oppstart pa Windows

```powershell
.\scripts\start.ps1
```

eller:

```bat
scripts\start.bat
```

## Førstegangsoppsett

1. Start appen.
2. Gå til `http://127.0.0.1:8000/bootstrap-admin`.
3. Opprett lokal adminbruker.
4. Logg inn.

## Voucher-basert posting

1. Gå til `Vouchers -> Ny voucher`.
2. Fyll ut metadata og linjer som JSON-array.
3. Linjene må balansere (`sum(debet) == sum(kredit)`).
4. For MVA-linjer bruk:
   - `vat_mva_code`
   - `vat_rate`
   - `vat_base_nok`
   - `vat_amount_nok`
5. Systemet validerer beregnede `mvaKode`-linjer og whole-NOK regler.

## Legacy-migrering (engangskjøring)

Migrerer `incomes/expenses` til vouchers/linjer, oppretter bilag-hashposter og lenker.

Via UI:
- `Settings -> Legacy-migrering -> Kjør`

Via CLI:

```powershell
.\.venv\Scripts\python.exe -m app.migrate_legacy
```

## MVA term-datasett (Jan/Feb eksempel)

### Via UI

1. Gå til `Rapporter`.
2. Velg `Ar` og `Termin` (f.eks. termin 1 = Jan-Feb).
3. Last ned:
   - PDF: `/reports/mva`
   - JSON dataset: `/reports/mva/json`
   - CSV: `/reports/mva/csv`

### Via curl

```powershell
curl.exe -X POST -F "year=2026" -F "term=1" http://127.0.0.1:8000/reports/mva/json -o vat_term_dataset.json
```

JSON inneholder:
- `mvaKode`
- `grunnlag_nok` (hele NOK)
- `sats`
- `merverdiavgift_nok` (hele NOK)
- `drilldown` med underliggende vouchers/linjer/bilag

## Rapporter

- Arsoversikt (PDF): `/reports/yearly`
- MVA-spesifikasjon/termin (PDF/JSON/CSV): `/reports/mva`, `/reports/mva/json`, `/reports/mva/csv`
- Bokforingsspesifikasjon (PDF/CSV): `/reports/journal/pdf`, `/reports/journal/csv`
- Kontospesifikasjon (PDF/CSV): `/reports/accounts/pdf`, `/reports/accounts/csv`

## Periodelaas og korreksjon

- Lås termin i `Settings`.
- Etter laas:
  - vanlige posteringer i perioden stoppes
  - oppdatering/sletting av vouchers/linjer i laast periode blokkeres
  - oppdatering/sletting av bilag lenket til laast periode blokkeres
  - korreksjon skjer via `Voucher -> Opprett korreksjon` (reversal + ny voucher)

## Backup / restore-verifisering

Lag backup:

```powershell
.\.venv\Scripts\python.exe -m app.backup_cli backup
```

Verifiser backup:

```powershell
.\.venv\Scripts\python.exe -m app.backup_cli verify --archive data\backups\backup_YYYYMMDD_HHMMSS.zip
```

Backup inkluderer:
- DB-fil (`app.db`)
- `data/attachments`
- `data/reports` (kan slås av med `--no-reports`)

## Tester

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Dekker bl.a.:
- voucher-balansering
- periodelaas
- korreksjonsflyt (reversal + ny voucher)
- MVA whole-NOK + floor-validering
- drilldown-data for MVA-linjer
