# Bidra til Mini Regnskap ENK

Takk for at du vil bidra. Dette prosjektet prioriterer stabil bokføringslogikk, lokal-first drift og tydelig dokumentasjon.

## Krav til utviklingsmiljø

- Python 3.11+
- Windows PowerShell eller tilsvarende terminal

## Sette opp lokalt miljø

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
$env:PYTHONPATH='.'
```

## Kjør appen lokalt

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Alternativt kan du bruke:

```powershell
.\scripts\start.ps1
```

## Kjør tester

```powershell
$env:PYTHONPATH='.'
pytest -q
```

## Grunnleggende kodestil

- Behold eksisterende regnskaps- og MVA-logikk urørt med mindre du retter en tydelig feil.
- Endringer i `app/ledger.py` eller `app/vat_engine.py` skal ha tester som dekker ny atferd.
- Bruk tydelige funksjonsnavn og typehint der det allerede brukes.
- Unngå nye skyavhengigheter; løsningen skal forbli lokal-first.
- All brukerrettet tekst skal være norsk bokmål.
- Hold endringer små og fokuserte per commit.

## Forslag til arbeidsflyt

1. Opprett branch fra `main`.
2. Gjør avgrensede endringer.
3. Kjør tester lokalt.
4. Oppdater dokumentasjon ved behov.
5. Send PR med kort beskrivelse av hva som er endret og hvorfor.

## Rapporter feil

- Beskriv forventet og faktisk resultat.
- Legg ved trinn for reproduksjon.
- Del aldri ekte regnskapsdata, hemmeligheter eller personopplysninger.

## Pre-commit-beskyttelse

Repoet har en lett pre-commit-hook i `.githooks/pre-commit` som stopper commit når staged endringer inneholder:

- databasefiler (`.db`, `.sqlite`, `.sqlite3`)
- `.env`-filer
- filer under `data/` (unntatt eksisterende `.gitkeep`)
- typiske hemmelighetsmønstre i nye linjer

Installer hook-oppsett én gang per klone:

```powershell
.\scripts\install-hooks.ps1
```

Alternativt manuelt:

```powershell
git config core.hooksPath .githooks
```

For macOS/Linux:

```bash
chmod +x .githooks/pre-commit
```

Verifiser at hook-path er satt:

```powershell
git config --get core.hooksPath
```

Forventet output:

```text
.githooks
```
