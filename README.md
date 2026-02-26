# Mini Regnskap ENK

Mini Regnskap ENK er et lokalt regnskapssystem for enkeltpersonforetak (ENK) i Norge. Applikasjonen kjører med FastAPI, Jinja og SQLite uten skykrav, og er laget for trygg, praktisk bokføring med bilag, MVA, periodelås og rapporter.

## Prosjektets visjon

Prosjektet er bygget for å gi små entreprenører i Norge et enkelt, lokalt og forståelig verktøy for regnskap i hverdagen. Målet er at koden skal være fri å lese, forstå og kjøre lokalt (source available), samtidig som kommersiell videredistribusjon styres av lisensvilkår. Videre utvikling prioriterer bedre brukerflyt, tydeligere kontroller for bokføringskvalitet og tryggere backup-/gjenopprettingsrutiner.

## Hva systemet gjør

- Bilagsføring med dobbel bokføring (`vouchers` + `voucher_lines`)
- Vedleggshåndtering for bilag (PDF/JPG/JPEG/PNG)
- MVA-grunnlag per termin og eksport (PDF, JSON, CSV)
- Årsrapport, journal og kontospesifikasjon
- Terminlås og korreksjonsflyt (reversering + korrigert bilag)
- Lokal innlogging med hashed passord og sesjoner
- Legacy-import fra eldre SQLite-database

## Lokal-first og ingen skyavhengigheter

- Data lagres lokalt i prosjektmappen (`data/`)
- Standard database er `data/app.db`
- Rapporter, vedlegg og backuper lagres lokalt i underkataloger
- Ingen automatisk synkronisering eller opplasting til skytjenester

## Teknologi

- Python 3.11+
- FastAPI + Jinja2
- SQLite
- ReportLab (PDF-generering)
- Pytest (tester)

## Kom i gang

### Alternativ 1: Oppstartsskript (Windows)

```powershell
.\scripts\start.ps1
```

eller:

```bat
scripts\start.bat
```

### Alternativ 2: Manuell oppstart

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Åpne deretter `http://127.0.0.1:8000/bootstrap-admin` for å opprette første adminbruker.

## Første gangs bruk

1. Opprett adminbruker på `/bootstrap-admin`.
2. Logg inn på `/login`.
3. Sett firmaopplysninger under `Innstillinger`.
4. Opprett bilag under `Bilag`.
5. Generer rapporter under `Rapporter`.
6. Lås termin når perioden er ferdig avstemt.

## Demo-data

Det finnes en enkel seeder for demo/testing:

```powershell
$env:PYTHONPATH='.'
python -m app.seed_demo
```

Se [DEMO_DATA.md](DEMO_DATA.md) for anbefalt trygg arbeidsflyt uten ekte data.

## Backup og gjenoppretting

Lag backup:

```powershell
$env:PYTHONPATH='.'
python -m app.backup_cli backup
```

Verifiser backup:

```powershell
$env:PYTHONPATH='.'
python -m app.backup_cli verify --archive data/backups/backup_YYYYMMDD_HHMMSS.zip
```

Anbefaling:

- Ta backup før migrering, større endringer og før terminlås
- Oppbevar minst én kryptert kopi utenfor arbeidsmaskinen
- Test gjenoppretting jevnlig i et separat testmiljø

## Arkitektur (kort oversikt)

- `app/main.py`: HTTP-ruter, sideflyt og validering av innsendt data
- `app/db.py`: databaseoppsett, katalogstruktur og migreringer
- `app/ledger.py`: kjernelogikk for bokføring, bilag og korreksjoner
- `app/vat_engine.py`: MVA-beregninger og MVA-datasett
- `app/pdf_reports.py`: PDF-rapporter
- `app/auth.py`: brukere, passordhashing og sesjoner
- `app/legacy_import.py` + `app/migrate_legacy.py`: import/migrering fra gammel modell
- `app/backup_cli.py`: CLI for backup og verifisering
- `data/`: lokal database, vedlegg, rapporter og backupfiler
- `tests/`: automatiske tester for ruter, ledger og MVA

## Test

```powershell
$env:PYTHONPATH='.'
pytest -q
```

## Sikkerhet

Hva som lagres lokalt:

- Bokføringsdata (bilag, linjer, perioder, innstillinger)
- Brukerkontoer med passordhash (ikke klartekstpassord)
- Vedlegg og genererte rapporter
- Revisjonsspor i databasen (`audit_log`)

Lokal-first håndtering:

- Ingen skykobling er nødvendig for normal bruk
- Data ligger i lokale filer under `data/`
- Tilgangsstyring skjer via lokal innlogging og sesjonscookie

Backup-anbefaling:

- Bruk innebygget backup-CLI
- Krypter backup ved ekstern lagring
- Behold flere historiske backupversjoner

Se [SECURITY.md](SECURITY.md) og [SECURITY_AUDIT_REPORT.md](SECURITY_AUDIT_REPORT.md) for mer detaljer.

## Lisens

Prosjektet er **source available** under **Business Source License 1.1 (BUSL-1.1)**. Dette er ikke en OSI-godkjent open source-lisens.

Lisensparametere for dette repoet:

- Change Date: `2029-02-26`
- Change License etter Change Date: `GPL-3.0-or-later`

Tillatt:

- Lese og inspisere kildekoden
- Kjøres lokalt i henhold til lisensvilkårene i `LICENSE`
- Intern bruk innenfor rammene av `Additional Use Grant`

Ikke tillatt uten separat avtale med rettighetshaver:

- Kommersiell videresalg eller redistribusjon av løsningen
- Tilby løsningen som tjeneste for tredjeparter utover lisensens grenser

Viktige referanser:

- Offisiell BUSL-tekst: <https://mariadb.com/bsl11/>
- Open Source Initiative (OSD): <https://opensource.org/osd>
- Gjeldende prosjektlisens: [LICENSE](LICENSE)

## Bidra

Se [CONTRIBUTING.md](CONTRIBUTING.md) for utvikleroppsett, testkrav og kodestil.
