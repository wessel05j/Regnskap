# CHANGELOG

## 2026-02-25 - Ledger/VAT compliance upgrade

### Added

- Versioned migration runner in `app/db.py` with `schema_migrations`.
- New accounting/security tables:
  - `accounts`
  - `fiscal_periods`
  - `vouchers`
  - `voucher_lines`
  - `bilag_files`
  - `audit_log`
  - `users`
  - `user_sessions`
  - `voucher_sequences`
- Locked-period DB triggers that block update/delete for vouchers and voucher lines in locked periods.
- VAT engine (`app/vat_engine.py`) with:
  - `mvaKode` rules
  - whole-NOK aggregation
  - validation for computed VAT lines (floor logic)
  - term dataset JSON export
  - drilldown data per aggregated line
- Ledger module (`app/ledger.py`) with:
  - double-entry voucher creation
  - voucher balancing validation
  - term locking
  - correction flow (reversal + corrected voucher)
  - audit log writes
  - statutory query helpers (journal/account specs)
  - yearly summary sourced from ledger
- Legacy migration CLI (`app/migrate_legacy.py`) converting `incomes/expenses` + attachments into vouchers/lines/bilag.
- Backup/verify CLI (`app/backup_cli.py`) for DB + attachments (+optional reports).
- Authentication module (`app/auth.py`) with hashed passwords + session tokens.
- New/updated routes in `app/main.py`:
  - Auth: `/login`, `/bootstrap-admin`, `/logout`
  - Voucher workflow: `/vouchers`, `/vouchers/new`, `/vouchers/{id}`, `/vouchers/{id}/correct`
  - Reports:
    - `/reports/yearly`
    - `/reports/mva`, `/reports/mva/json`, `/reports/mva/csv`, `/reports/mva/drilldown`
    - `/reports/journal/pdf`, `/reports/journal/csv`
    - `/reports/accounts/pdf`, `/reports/accounts/csv`
  - Settings admin actions:
    - `/settings/lock-term`
    - `/settings/run-legacy-migration`
  - Bilag download route: `/bilag/{bilag_id}`
- New templates:
  - `login.html`
  - `bootstrap_admin.html`
  - `vouchers_list.html`
  - `voucher_form.html`
  - `voucher_detail.html`
  - `voucher_correct.html`
- Updated templates for base nav, reports, settings, dashboard, and read-only legacy views.
- New tests in `tests/test_ledger_vat.py`.
- Migration `v4` (`locking_integrity`) that adds:
  - insert-block trigger for non-reversal vouchers in locked periods
  - insert-block trigger for non-reversal voucher lines in locked periods
  - `bilag_files` immutability triggers (update/delete blocked when linked to locked period)
  - term date normalization in `fiscal_periods` (including leap-year handling for term 1)

### Changed

- Existing yearly PDF now uses ledger data (not legacy income/expense sums).
- MVA term PDF now reports per `mvaKode` with drilldown appendix.
- Legacy `incomes/expenses` are read-only in app routes (no create/edit/delete).
- Startup DB initialization now applies explicit versioned migrations.

### Verification

- Test suite: `10 passed` via `python -m pytest -q`.

### Known limitations / next steps

- No SAF-T export yet.
- Voucher entry UI currently uses JSON line input (functional but basic).
- Single local admin model (no multi-role/2FA).
- No automated scheduler for backups (manual CLI command).
