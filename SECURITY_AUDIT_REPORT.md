# Sikkerhetsrevisjon (Security Audit Report)

Dato: 2026-02-26
Branch: `release-prep/source-available`

## Omfang

Revisjonen dekket:

- Arbeidstre (nåværende filer)
- Sporede filer i Git
- Filnavn i Git-historikk
- Innholdssøk i historikk etter vanlige nøkkelmønstre

## Sjekker som ble kjørt

Fil- og datamønstre:

- `.env`, `.env.*`
- `*.db`, `*.sqlite`, `*.sqlite3`
- `data/attachments`, `data/reports`, `data/backups`

Nøkkel-/hemmelighetsmønstre (regex):

- `AKIA...` (AWS access key-id)
- `BEGIN ... PRIVATE KEY`
- `aws_secret_access_key`
- `ghp_...` (GitHub token)
- `xox...` (Slack token)
- `AIza...` (Google API key)

## Funn

1. **Ingen sporede hemmeligheter funnet i repoets nåværende filer.**
2. **Ingen treff i historikk-søk på vanlige token-/nøkkelmønstre.**
3. **Ingen sporede `.env`/`.db`-filer i Git-historikk**, utover forventede katalogmarkører (`.gitkeep`) i:
   - `data/attachments/.gitkeep`
   - `data/reports/.gitkeep`
   - `data/backups/.gitkeep`
4. **Lokale datafiler finnes i arbeidstre** (f.eks. `data/app.db`, rapportfiler), men disse er ignorert via `.gitignore`.

## Tiltak utført

- Forsterket `.gitignore` med ekstra mønstre for:
  - SQLite sidefiler (`*.db-journal`, `*.sqlite-journal`, `*.sqlite-wal`, `*.sqlite-shm`)
  - Nøkkel-/sertifikatfiler (`*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.crt`, `*.der`)
- Oppdatert dokumentasjon med tydelig sikkerhetskapittel i `README.md`.
- Lagt til `SECURITY.md` med ansvarlig rapporteringsprosess.

## Vurdering

Basert på kjørte kontroller er det **ingen konkrete indikasjoner på committed secrets** i nåværende historikk.

## Plan hvis hemmeligheter senere oppdages i historikk (ikke kjørt)

Historikk-rewrite skal kun utføres etter eksplisitt godkjenning, for eksempel med flagg: `ALLOW_HISTORY_REWRITE=1`.

### Alternativ A: `git filter-repo`

```bash
# 1) Ta backup av repo først
git clone --mirror <repo-url> repo-backup.git

# 2) Fjern sensitive filer fra all historikk
git filter-repo --path .env --path-glob '*.db' --path-glob '*.sqlite*' --invert-paths

# 3) Erstatt hemmeligheter i innhold via replacement-fil
# replacements.txt format: 'før==>etter'
git filter-repo --replace-text replacements.txt

# 4) Tving oppdatert historikk til remote
git push --force --all
git push --force --tags
```

### Alternativ B: BFG Repo-Cleaner

```bash
# Fjern filer
java -jar bfg.jar --delete-files '{.env,*.db,*.sqlite,*.sqlite3}'

# Erstatt hemmeligheter
java -jar bfg.jar --replace-text replacements.txt

# Rydd og push
git reflog expire --expire=now --all
git gc --prune=now --aggressive
git push --force --all
git push --force --tags
```

## Merknad

Historikk-rewrite er **ikke utført** i denne leveransen.

