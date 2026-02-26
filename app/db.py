from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
ATTACHMENTS_DIR = DATA_DIR / "attachments"
REPORTS_DIR = DATA_DIR / "reports"
BACKUPS_DIR = DATA_DIR / "backups"
LOG_FILE = DATA_DIR / "app.log"

_DB_PATH = Path(os.getenv("REGNSKAP_DB_PATH", DATA_DIR / "app.db"))


def configure_database(path: str | Path) -> None:
    global _DB_PATH
    _DB_PATH = Path(path)


def get_db_path() -> Path:
    return _DB_PATH


def ensure_data_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    ensure_data_dirs()
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migration_1_legacy_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            company_name TEXT NOT NULL DEFAULT 'Eksempel ENK',
            org_number TEXT,
            default_currency TEXT NOT NULL DEFAULT 'NOK',
            default_vat_rate REAL NOT NULL DEFAULT 25.0,
            default_output_vat_rate REAL NOT NULL DEFAULT 0.0,
            primary_income_model TEXT NOT NULL DEFAULT 'Salg av digitale tjenester',
            vat_registered_from TEXT
        );

        INSERT OR IGNORE INTO settings (
            id, company_name, org_number, default_currency, default_vat_rate, default_output_vat_rate, primary_income_model, vat_registered_from
        ) VALUES (
            1, 'Eksempel ENK', '', 'NOK', 25.0, 0.0, 'Salg av digitale tjenester', NULL
        );

        CREATE TABLE IF NOT EXISTS incomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            amount_original REAL NOT NULL,
            currency TEXT NOT NULL,
            amount_nok REAL,
            exchange_rate REAL,
            source TEXT NOT NULL,
            note TEXT,
            attachment_stored_name TEXT,
            attachment_original_name TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            vendor TEXT NOT NULL,
            category TEXT NOT NULL,
            amount_original REAL NOT NULL,
            currency TEXT NOT NULL,
            amount_nok REAL,
            exchange_rate REAL,
            vat_amount REAL,
            payment_method TEXT NOT NULL,
            note TEXT,
            attachment_stored_name TEXT,
            attachment_original_name TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    columns = [row["name"] for row in conn.execute("PRAGMA table_info(settings)").fetchall()]
    if "default_output_vat_rate" not in columns:
        conn.execute("ALTER TABLE settings ADD COLUMN default_output_vat_rate REAL NOT NULL DEFAULT 0.0")


def _migration_2_ledger_and_security(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS accounts (
            account_no TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            account_type TEXT NOT NULL CHECK (account_type IN ('ASSET', 'LIABILITY', 'EQUITY', 'INCOME', 'EXPENSE')),
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
        );

        CREATE TABLE IF NOT EXISTS fiscal_periods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER NOT NULL,
            period_type TEXT NOT NULL CHECK (period_type IN ('term', 'month', 'year')),
            period_no INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            is_locked INTEGER NOT NULL DEFAULT 0 CHECK (is_locked IN (0, 1)),
            locked_at TEXT,
            locked_by TEXT,
            UNIQUE (year, period_type, period_no)
        );

        CREATE TABLE IF NOT EXISTS bilag_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stored_name TEXT NOT NULL UNIQUE,
            original_name TEXT NOT NULL,
            mime_type TEXT,
            file_size INTEGER NOT NULL DEFAULT 0,
            sha256 TEXT NOT NULL,
            uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            uploaded_by TEXT NOT NULL DEFAULT 'system'
        );

        CREATE TABLE IF NOT EXISTS voucher_sequences (
            series TEXT PRIMARY KEY,
            last_no INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS vouchers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            voucher_series TEXT NOT NULL DEFAULT 'A',
            voucher_no INTEGER NOT NULL,
            voucher_type TEXT NOT NULL,
            document_date TEXT NOT NULL,
            posting_date TEXT NOT NULL,
            counterparty_name TEXT,
            counterparty_id TEXT,
            currency TEXT NOT NULL DEFAULT 'NOK',
            exchange_rate REAL,
            total_nok INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT NOT NULL DEFAULT 'system',
            status TEXT NOT NULL DEFAULT 'posted' CHECK (status IN ('posted', 'reversed')),
            reversal_of_voucher_id INTEGER REFERENCES vouchers(id),
            correction_of_voucher_id INTEGER REFERENCES vouchers(id),
            bilag_id INTEGER REFERENCES bilag_files(id),
            legacy_source TEXT UNIQUE,
            description TEXT,
            UNIQUE (voucher_series, voucher_no)
        );

        CREATE TABLE IF NOT EXISTS voucher_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            voucher_id INTEGER NOT NULL REFERENCES vouchers(id) ON DELETE RESTRICT,
            line_no INTEGER NOT NULL,
            account_no TEXT NOT NULL REFERENCES accounts(account_no),
            debit_nok INTEGER NOT NULL DEFAULT 0 CHECK (debit_nok >= 0),
            credit_nok INTEGER NOT NULL DEFAULT 0 CHECK (credit_nok >= 0),
            description TEXT,
            vat_mva_code TEXT,
            vat_rate REAL,
            vat_base_nok INTEGER,
            vat_amount_nok INTEGER,
            bilag_id INTEGER REFERENCES bilag_files(id),
            legacy_row_type TEXT,
            legacy_row_id INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK ((debit_nok = 0 AND credit_nok > 0) OR (credit_nok = 0 AND debit_nok > 0)),
            UNIQUE (voucher_id, line_no)
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT,
            before_json TEXT,
            after_json TEXT,
            reason TEXT
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 1 CHECK (is_admin IN (0, 1)),
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS user_sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_vouchers_posting_date ON vouchers(posting_date);
        CREATE INDEX IF NOT EXISTS idx_voucher_lines_voucher_id ON voucher_lines(voucher_id);
        CREATE INDEX IF NOT EXISTS idx_voucher_lines_account_no ON voucher_lines(account_no);
        CREATE INDEX IF NOT EXISTS idx_voucher_lines_vat_code ON voucher_lines(vat_mva_code);
        CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type, entity_id);

        CREATE TRIGGER IF NOT EXISTS trg_lock_vouchers_update
        BEFORE UPDATE ON vouchers
        WHEN EXISTS (
            SELECT 1
            FROM fiscal_periods p
            WHERE p.is_locked = 1
              AND OLD.posting_date BETWEEN p.start_date AND p.end_date
        )
        BEGIN
            SELECT RAISE(ABORT, 'Locked period: vouchers are immutable');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_lock_vouchers_delete
        BEFORE DELETE ON vouchers
        WHEN EXISTS (
            SELECT 1
            FROM fiscal_periods p
            WHERE p.is_locked = 1
              AND OLD.posting_date BETWEEN p.start_date AND p.end_date
        )
        BEGIN
            SELECT RAISE(ABORT, 'Locked period: vouchers are immutable');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_lock_voucher_lines_update
        BEFORE UPDATE ON voucher_lines
        WHEN EXISTS (
            SELECT 1
            FROM vouchers v
            JOIN fiscal_periods p ON v.posting_date BETWEEN p.start_date AND p.end_date
            WHERE p.is_locked = 1
              AND v.id = OLD.voucher_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'Locked period: voucher lines are immutable');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_lock_voucher_lines_delete
        BEFORE DELETE ON voucher_lines
        WHEN EXISTS (
            SELECT 1
            FROM vouchers v
            JOIN fiscal_periods p ON v.posting_date BETWEEN p.start_date AND p.end_date
            WHERE p.is_locked = 1
              AND v.id = OLD.voucher_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'Locked period: voucher lines are immutable');
        END;
        """
    )

    chart = [
        ("1500", "Kundefordringer", "ASSET"),
        ("1920", "Bankinnskudd", "ASSET"),
        ("2050", "Egenkapital", "EQUITY"),
        ("2400", "Leverandorgjeld", "LIABILITY"),
        ("2710", "Utgaende MVA", "LIABILITY"),
        ("2720", "Inngaende MVA", "ASSET"),
        ("3000", "Salgsinntekt, avgiftspliktig", "INCOME"),
        ("3100", "Salgsinntekt, avgiftsfri", "INCOME"),
        ("4000", "Varekjop", "EXPENSE"),
        ("5000", "Andre driftskostnader", "EXPENSE"),
        ("7790", "Annen kostnad", "EXPENSE"),
    ]
    conn.executemany(
        """
        INSERT OR IGNORE INTO accounts (account_no, name, account_type, active)
        VALUES (?, ?, ?, 1)
        """,
        chart,
    )


def _migration_3_seed_fiscal_terms(conn: sqlite3.Connection) -> None:
    base_year = date.today().year
    years = [base_year - 1, base_year, base_year + 1]
    term_ranges = (
        (1, "01-01", "02-28"),
        (2, "03-01", "04-30"),
        (3, "05-01", "06-30"),
        (4, "07-01", "08-31"),
        (5, "09-01", "10-31"),
        (6, "11-01", "12-31"),
    )
    for year in years:
        for period_no, start_mmdd, end_mmdd in term_ranges:
            start_date = f"{year}-{start_mmdd}"
            end_date = f"{year}-{end_mmdd}"
            conn.execute(
                """
                INSERT OR IGNORE INTO fiscal_periods (
                    year, period_type, period_no, start_date, end_date, is_locked
                ) VALUES (?, 'term', ?, ?, ?, 0)
                """,
                (year, period_no, start_date, end_date),
            )


def _migration_4_locking_integrity(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_vouchers_bilag_id ON vouchers(bilag_id);
        CREATE INDEX IF NOT EXISTS idx_voucher_lines_bilag_id ON voucher_lines(bilag_id);

        CREATE TRIGGER IF NOT EXISTS trg_lock_vouchers_insert
        BEFORE INSERT ON vouchers
        WHEN LOWER(NEW.voucher_type) != 'reversal'
          AND EXISTS (
              SELECT 1
              FROM fiscal_periods p
              WHERE p.is_locked = 1
                AND NEW.posting_date BETWEEN p.start_date AND p.end_date
          )
        BEGIN
            SELECT RAISE(ABORT, 'Locked period: only reversal vouchers are allowed');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_lock_voucher_lines_insert
        BEFORE INSERT ON voucher_lines
        WHEN EXISTS (
            SELECT 1
            FROM vouchers v
            JOIN fiscal_periods p ON v.posting_date BETWEEN p.start_date AND p.end_date
            WHERE p.is_locked = 1
              AND v.id = NEW.voucher_id
              AND LOWER(v.voucher_type) != 'reversal'
        )
        BEGIN
            SELECT RAISE(ABORT, 'Locked period: voucher lines are immutable');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_lock_bilag_files_update
        BEFORE UPDATE ON bilag_files
        WHEN EXISTS (
            SELECT 1
            FROM vouchers v
            JOIN fiscal_periods p ON v.posting_date BETWEEN p.start_date AND p.end_date
            WHERE p.is_locked = 1
              AND (
                v.bilag_id = OLD.id
                OR EXISTS (
                    SELECT 1
                    FROM voucher_lines vl
                    WHERE vl.voucher_id = v.id
                      AND vl.bilag_id = OLD.id
                )
              )
        )
        BEGIN
            SELECT RAISE(ABORT, 'Locked period: bilag is immutable');
        END;

        CREATE TRIGGER IF NOT EXISTS trg_lock_bilag_files_delete
        BEFORE DELETE ON bilag_files
        WHEN EXISTS (
            SELECT 1
            FROM vouchers v
            JOIN fiscal_periods p ON v.posting_date BETWEEN p.start_date AND p.end_date
            WHERE p.is_locked = 1
              AND (
                v.bilag_id = OLD.id
                OR EXISTS (
                    SELECT 1
                    FROM voucher_lines vl
                    WHERE vl.voucher_id = v.id
                      AND vl.bilag_id = OLD.id
                )
              )
        )
        BEGIN
            SELECT RAISE(ABORT, 'Locked period: bilag is immutable');
        END;
        """
    )

    conn.execute(
        """
        UPDATE fiscal_periods
        SET start_date = printf('%04d-01-01', year),
            end_date = printf(
                '%04d-02-%02d',
                year,
                CASE
                    WHEN (year % 4 = 0 AND (year % 100 != 0 OR year % 400 = 0)) THEN 29
                    ELSE 28
                END
            )
        WHERE period_type = 'term'
          AND period_no = 1
        """
    )

    conn.execute(
        """
        UPDATE fiscal_periods
        SET start_date = printf('%04d-03-01', year),
            end_date = printf('%04d-04-30', year)
        WHERE period_type = 'term'
          AND period_no = 2
        """
    )
    conn.execute(
        """
        UPDATE fiscal_periods
        SET start_date = printf('%04d-05-01', year),
            end_date = printf('%04d-06-30', year)
        WHERE period_type = 'term'
          AND period_no = 3
        """
    )
    conn.execute(
        """
        UPDATE fiscal_periods
        SET start_date = printf('%04d-07-01', year),
            end_date = printf('%04d-08-31', year)
        WHERE period_type = 'term'
          AND period_no = 4
        """
    )
    conn.execute(
        """
        UPDATE fiscal_periods
        SET start_date = printf('%04d-09-01', year),
            end_date = printf('%04d-10-31', year)
        WHERE period_type = 'term'
          AND period_no = 5
        """
    )
    conn.execute(
        """
        UPDATE fiscal_periods
        SET start_date = printf('%04d-11-01', year),
            end_date = printf('%04d-12-31', year)
        WHERE period_type = 'term'
          AND period_no = 6
        """
    )


MIGRATIONS: list[tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (1, "legacy_tables", _migration_1_legacy_tables),
    (2, "ledger_security", _migration_2_ledger_and_security),
    (3, "seed_fiscal_terms", _migration_3_seed_fiscal_terms),
    (4, "locking_integrity", _migration_4_locking_integrity),
]


def _ensure_schema_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {int(row["version"]) for row in rows}


def init_db() -> None:
    ensure_data_dirs()
    conn = get_connection()
    try:
        _ensure_schema_migrations(conn)
        applied = _applied_versions(conn)
        for version, name, migration_fn in MIGRATIONS:
            if version in applied:
                continue
            migration_fn(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                (version, name),
            )
            conn.commit()
    finally:
        conn.close()
