# Mini Regnskap ENK

A local-first bookkeeping system for Norwegian sole proprietorships (ENK), built with FastAPI, Jinja, and SQLite.

Mini Regnskap ENK is designed for operators who want full control of accounting data on their own machine, without cloud lock-in.

## Status and Scope

- Current maturity: **not production ready**
- Intended use: local evaluation, development, and controlled pilot usage
- No guarantee of regulatory completeness for all accounting scenarios
- No automatic Altinn submission or external filing integration

This repository is public for transparency and collaboration, but should not yet be treated as a finished production accounting product.

## Production Warning

Do not deploy this system as a business-critical production accounting platform yet.

- Security hardening is still in progress
- Operational controls (monitoring, incident response, disaster recovery) are not complete
- The current release process is aimed at development/testing, not regulated production operations

## License (Source Available)

This project is **source available** under the **Business Source License 1.1 (BUSL-1.1)**.

- You can inspect the code and run it locally under the license terms
- Commercial redistribution and commercial service usage are restricted without separate permission
- Change Date for this repository: **2029-02-26**
- Full terms: [LICENSE](LICENSE)

References:

- BUSL text: <https://mariadb.com/bsl11/>
- OSI (Open Source Definition): <https://opensource.org/osd>

## Development Model

Active development happens in the **`development`** branch.

Recommended branch flow:

- `development`: day-to-day feature work, refactoring, and integration
- `main`: curated, stable snapshots for broader testing and public visibility

## Why Local-First

- Accounting records remain on your own device
- No mandatory cloud dependency for normal operation
- Offline-friendly workflow for daily bookkeeping
- Easier data ownership, backup control, and audit traceability

## No Cloud Storage

Mini Regnskap ENK does **not** require cloud storage.

By default, data is stored in local project folders:

- Database: `data/app.db`
- Attachments: `data/attachments/`
- Generated reports: `data/reports/`
- Backup archives: `data/backups/`
- Automatic startup snapshots: `data/backups/startup_*.db` (when transactional data exists)

## Core Capabilities

- Voucher registration with double-entry accounting
- VAT term aggregation and VAT exports (PDF/JSON/CSV)
- Yearly report, journal report, and account specification
- Period locking and correction flow (reversal + corrected voucher)
- Local authentication (password hashing + session tokens)
- Legacy import/migration from older SQLite format
- Backup and backup verification CLI

## Architecture Overview

### Runtime Stack

- Backend/API: FastAPI
- UI rendering: Jinja templates
- Storage: SQLite
- Report generation: ReportLab
- Test suite: Pytest

### Project Structure

- `app/main.py`: route layer, request handling, UI/API flow
- `app/db.py`: database setup, migrations, data directory management
- `app/ledger.py`: accounting engine and voucher logic
- `app/vat_engine.py`: VAT calculations and VAT datasets
- `app/pdf_reports.py`: PDF report generation
- `app/auth.py`: users, password hashing, session handling
- `app/legacy_import.py` and `app/migrate_legacy.py`: migration/import workflows
- `app/backup_cli.py`: backup and verification commands
- `tests/`: automated coverage for core accounting and routes

### Data Flow (High Level)

1. User submits voucher/report action in UI.
2. FastAPI validates and routes request.
3. Ledger/VAT modules process accounting logic.
4. SQLite persists records and audit trail.
5. Reports and exports are generated locally in `data/reports/`.

## Quick Start

### Option A (Windows helper script)

```powershell
.\scripts\start.ps1
```

or:

```bat
scripts\start.bat
```

### Option B (manual)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Then open `http://127.0.0.1:8000/bootstrap-admin` to create the first admin account.

## Security and Local Data Control

Security fundamentals in this project:

- Local storage by default; no cloud transport required
- Passwords are stored as hashes, never plaintext
- Session-based authentication
- Audit log table for traceability
- Backup and backup verification tooling

Operational recommendations:

- Keep machine-level disk encryption enabled
- Restrict local OS account access
- Run regular encrypted backups
- Keep automatic startup snapshots enabled (configure with `REGNSKAP_STARTUP_BACKUP_KEEP` and `REGNSKAP_STARTUP_BACKUP_MIN_INTERVAL_MINUTES`)
- Test restore procedures in a separate environment
- Never commit real accounting data or secrets to Git

See also:

- [SECURITY.md](SECURITY.md)

### Pre-commit Guard

This repository includes a lightweight pre-commit hook at `.githooks/pre-commit` to block commits that include:

- `.db`/`.sqlite` artifacts
- `.env` files
- `data/` folder contents (except tracked `.gitkeep` placeholders)
- high-confidence secret patterns in staged diff lines

Install once per clone:

```powershell
.\scripts\install-hooks.ps1
```

Or manually:

```powershell
git config core.hooksPath .githooks
```

On macOS/Linux, ensure execute permission:

```bash
chmod +x .githooks/pre-commit
```

Verification:

```powershell
git config --get core.hooksPath
```

Expected output:

```text
.githooks
```

## Roadmap

Planned priorities:

- Hardening and security review for production-readiness
- Improved bookkeeping validation and guardrails
- Better error handling and operator diagnostics
- Expanded test coverage for edge cases in ledger/VAT flows
- Improved import/export UX for accountants and auditors
- Release packaging and upgrade/migration tooling

## Screenshots (Placeholders)

- `[Placeholder] Dashboard`: `docs/screenshots/dashboard.png`
- `[Placeholder] New Voucher Form`: `docs/screenshots/voucher-form.png`
- `[Placeholder] VAT Report`: `docs/screenshots/vat-report.png`
- `[Placeholder] Settings`: `docs/screenshots/settings.png`
- `[Placeholder] Legacy Import`: `docs/screenshots/legacy-import.png`

Use anonymized demo data only when generating screenshots.

## Demo Data and Contribution

- Demo data guide: [DEMO_DATA.md](DEMO_DATA.md)
- Contribution guide: [CONTRIBUTING.md](CONTRIBUTING.md)

## Transparency Note

This repository is published to share implementation details and enable responsible collaboration. It is source available, local-first, and security-conscious, but still under active development and not yet production ready.
