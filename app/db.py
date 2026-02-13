from __future__ import annotations

import os
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
ATTACHMENTS_DIR = DATA_DIR / "attachments"
REPORTS_DIR = DATA_DIR / "reports"
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


def get_connection() -> sqlite3.Connection:
    ensure_data_dirs()
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    ensure_data_dirs()
    conn = get_connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                company_name TEXT NOT NULL DEFAULT 'Wessel Media',
                org_number TEXT,
                default_currency TEXT NOT NULL DEFAULT 'NOK',
                default_vat_rate REAL NOT NULL DEFAULT 25.0,
                default_output_vat_rate REAL NOT NULL DEFAULT 0.0,
                primary_income_model TEXT NOT NULL DEFAULT 'Eksport av digitale tjenester (Google Ireland)',
                vat_registered_from TEXT
            );

            INSERT OR IGNORE INTO settings (
                id, company_name, org_number, default_currency, default_vat_rate, default_output_vat_rate, primary_income_model, vat_registered_from
            ) VALUES (
                1, 'Wessel Media', '', 'NOK', 25.0, 0.0, 'Eksport av digitale tjenester (Google Ireland)', NULL
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
        conn.commit()
    finally:
        conn.close()
