# Demo-data for Mini Regnskap ENK

Denne guiden viser hvordan du fyller systemet med testdata uten å bruke ekte regnskapsinformasjon.

## Viktig før du starter

- Bruk aldri ekte personopplysninger, kontonummer eller bilag i demo.
- Kjør demo i en separat databasefil.
- Ta backup av aktiv database før du tester.

## 1. Sett egen demo-database

```powershell
$env:REGNSKAP_DB_PATH='data/demo_app.db'
$env:PYTHONPATH='.'
```

Dette gjør at appen bruker `data/demo_app.db` i stedet for standard `data/app.db`.

## 2. Seed demo-data

```powershell
python -m app.seed_demo
```

Seederen legger inn eksempelinntekter og eksempelutgifter for test.

## 3. Start appen mot demo-data

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Gå til `http://127.0.0.1:8000/bootstrap-admin` og opprett en midlertidig demo-bruker.

## 4. Rydd opp etter demo

```powershell
Remove-Item data/demo_app.db -ErrorAction SilentlyContinue
Remove-Item Env:REGNSKAP_DB_PATH -ErrorAction SilentlyContinue
```

## Tips

- Behold demo-data og produksjonsdata adskilt.
- Legg demo-skjermbilder i `docs/screenshots/` uten kundedata.
- Del bare anonymiserte data ved feilrapportering.
