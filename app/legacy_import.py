from __future__ import annotations

import os
import re
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app import db, migrate_legacy

VALID_DB_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
LEGACY_TABLES_REQUIRED_COLUMNS: dict[str, set[str]] = {
    "settings": {
        "id",
        "company_name",
        "org_number",
        "default_currency",
        "default_vat_rate",
        "default_output_vat_rate",
        "primary_income_model",
        "vat_registered_from",
    },
    "incomes": {
        "id",
        "date",
        "amount_original",
        "currency",
        "amount_nok",
        "exchange_rate",
        "source",
        "note",
        "attachment_stored_name",
        "attachment_original_name",
    },
    "expenses": {
        "id",
        "date",
        "vendor",
        "category",
        "amount_original",
        "currency",
        "amount_nok",
        "exchange_rate",
        "vat_amount",
        "payment_method",
        "note",
        "attachment_stored_name",
        "attachment_original_name",
    },
}
_LOCAL_DIR_PATTERN = re.compile(r"(regnskap|enk|wessel|mini)", re.IGNORECASE)
_IMPORT_LOCK = threading.Lock()


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


@contextmanager
def _temporary_db_path(path: Path):
    original = db.get_db_path()
    db.configure_database(path)
    try:
        yield
    finally:
        db.configure_database(original)


def _sqlite_open(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def validate_legacy_schema(path: str | Path) -> list[str]:
    candidate = Path(path).expanduser()
    errors: list[str] = []
    if not candidate.exists() or not candidate.is_file():
        return [f"Fil ikke funnet: {candidate}"]
    if candidate.suffix.lower() not in VALID_DB_SUFFIXES:
        return [f"Ugyldig filtype: {candidate.suffix}. Tillatt: .db, .sqlite, .sqlite3"]

    try:
        conn = _sqlite_open(candidate)
    except sqlite3.DatabaseError as exc:
        return [f"Kunne ikke lese SQLite-fil: {exc}"]

    try:
        for table_name, required_columns in LEGACY_TABLES_REQUIRED_COLUMNS.items():
            columns = _table_columns(conn, table_name)
            if not columns:
                errors.append(f"Mangler tabell: {table_name}")
                continue
            missing = required_columns - columns
            if missing:
                missing_text = ", ".join(sorted(missing))
                errors.append(f"Tabell {table_name} mangler kolonner: {missing_text}")
    finally:
        conn.close()
    return errors


def _existing_legacy_ids(prefix: str) -> set[int]:
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT legacy_source FROM vouchers WHERE legacy_source LIKE ?",
            (f"{prefix}:%",),
        ).fetchall()
    finally:
        conn.close()

    result: set[int] = set()
    for row in rows:
        value = str(row["legacy_source"] or "")
        parts = value.split(":", maxsplit=1)
        if len(parts) != 2:
            continue
        try:
            result.add(int(parts[1]))
        except ValueError:
            continue
    return result


def preview_legacy_database(path: str | Path) -> dict[str, Any]:
    candidate = Path(path).expanduser().resolve()
    errors = validate_legacy_schema(candidate)
    preview: dict[str, Any] = {
        "path": str(candidate),
        "errors": errors,
        "valid": len(errors) == 0,
        "settings_rows": 0,
        "incomes_rows": 0,
        "expenses_rows": 0,
        "incomes_new": 0,
        "expenses_new": 0,
        "incomes_existing": 0,
        "expenses_existing": 0,
        "is_current_db": candidate == db.get_db_path().resolve(),
    }
    if errors:
        return preview

    conn = _sqlite_open(candidate)
    try:
        preview["settings_rows"] = int(conn.execute("SELECT COUNT(*) AS c FROM settings").fetchone()["c"])
        income_ids = [int(row["id"]) for row in conn.execute("SELECT id FROM incomes").fetchall()]
        expense_ids = [int(row["id"]) for row in conn.execute("SELECT id FROM expenses").fetchall()]
    finally:
        conn.close()

    existing_income_ids = _existing_legacy_ids("income")
    existing_expense_ids = _existing_legacy_ids("expense")

    income_overlap = len([income_id for income_id in income_ids if income_id in existing_income_ids])
    expense_overlap = len([expense_id for expense_id in expense_ids if expense_id in existing_expense_ids])

    preview["incomes_rows"] = len(income_ids)
    preview["expenses_rows"] = len(expense_ids)
    preview["incomes_existing"] = income_overlap
    preview["expenses_existing"] = expense_overlap
    preview["incomes_new"] = max(0, len(income_ids) - income_overlap)
    preview["expenses_new"] = max(0, len(expense_ids) - expense_overlap)
    return preview


def _copy_legacy_rows_into_stage(*, source_db: Path, stage_db: Path, import_settings: bool) -> None:
    source_abs = source_db.resolve()
    stage_abs = stage_db.resolve()
    conn = _sqlite_open(stage_abs)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("ATTACH DATABASE ? AS legacy_src", (str(source_abs),))
        if import_settings:
            conn.execute(
                """
                UPDATE settings
                SET company_name = COALESCE((SELECT company_name FROM legacy_src.settings WHERE id = 1), company_name),
                    org_number = COALESCE((SELECT org_number FROM legacy_src.settings WHERE id = 1), org_number),
                    default_currency = COALESCE((SELECT default_currency FROM legacy_src.settings WHERE id = 1), default_currency),
                    default_vat_rate = COALESCE((SELECT default_vat_rate FROM legacy_src.settings WHERE id = 1), default_vat_rate),
                    default_output_vat_rate = COALESCE((SELECT default_output_vat_rate FROM legacy_src.settings WHERE id = 1), default_output_vat_rate),
                    primary_income_model = COALESCE((SELECT primary_income_model FROM legacy_src.settings WHERE id = 1), primary_income_model),
                    vat_registered_from = COALESCE((SELECT vat_registered_from FROM legacy_src.settings WHERE id = 1), vat_registered_from)
                WHERE settings.id = 1
                """
            )

        conn.execute(
            """
            INSERT OR IGNORE INTO incomes (
                id, date, amount_original, currency, amount_nok, exchange_rate, source, note,
                attachment_stored_name, attachment_original_name, created_at, updated_at
            )
            SELECT
                id, date, amount_original, currency, amount_nok, exchange_rate, source, note,
                attachment_stored_name, attachment_original_name,
                COALESCE(created_at, CURRENT_TIMESTAMP),
                COALESCE(updated_at, CURRENT_TIMESTAMP)
            FROM legacy_src.incomes
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO expenses (
                id, date, vendor, category, amount_original, currency, amount_nok, exchange_rate,
                vat_amount, payment_method, note, attachment_stored_name, attachment_original_name, created_at, updated_at
            )
            SELECT
                id, date, vendor, category, amount_original, currency, amount_nok, exchange_rate,
                vat_amount, payment_method, note, attachment_stored_name, attachment_original_name,
                COALESCE(created_at, CURRENT_TIMESTAMP),
                COALESCE(updated_at, CURRENT_TIMESTAMP)
            FROM legacy_src.expenses
            """
        )
        conn.execute("DETACH DATABASE legacy_src")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def import_legacy_database(*, source_path: str | Path, actor: str, import_settings: bool = False) -> dict[str, Any]:
    source_db = Path(source_path).expanduser().resolve()
    schema_errors = validate_legacy_schema(source_db)
    if schema_errors:
        raise ValueError("; ".join(schema_errors))

    with _IMPORT_LOCK:
        db.init_db()
        current_db = db.get_db_path().resolve()
        if not current_db.exists():
            raise ValueError(f"Aktiv database finnes ikke: {current_db}")

        stage_db = db.BACKUPS_DIR / f"legacy_stage_{_timestamp()}_{uuid4().hex}.db"
        pre_import_backup = db.BACKUPS_DIR / f"pre_legacy_import_{_timestamp()}.db"
        preview = preview_legacy_database(source_db)

        shutil.copy2(current_db, stage_db)
        try:
            _copy_legacy_rows_into_stage(source_db=source_db, stage_db=stage_db, import_settings=import_settings)
            with _temporary_db_path(stage_db):
                db.init_db()
                migration_result = migrate_legacy.run_legacy_migration(actor=actor)
                conn = db.get_connection()
                try:
                    ok_row = conn.execute("PRAGMA integrity_check").fetchone()
                    integrity_ok = bool(ok_row and str(ok_row[0]).lower() == "ok")
                finally:
                    conn.close()
                if not integrity_ok:
                    raise ValueError("Integritetskontroll feilet for staging-database.")

            shutil.copy2(current_db, pre_import_backup)
            os.replace(stage_db, current_db)
            return {
                "source_path": str(source_db),
                "backup_path": str(pre_import_backup),
                "import_settings": bool(import_settings),
                "preview": preview,
                "migration": migration_result,
            }
        except Exception:
            if stage_db.exists():
                stage_db.unlink()
            raise


def discover_legacy_candidates() -> list[Path]:
    roots = {
        db.BASE_DIR,
        db.DATA_DIR,
        db.BACKUPS_DIR,
        db.BASE_DIR / "backups",
    }
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        local_root = Path(local_app_data)
        if local_root.exists():
            for folder in local_root.iterdir():
                if folder.is_dir() and _LOCAL_DIR_PATTERN.search(folder.name):
                    roots.add(folder)

    found: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for suffix in VALID_DB_SUFFIXES:
            for path in root.rglob(f"*{suffix}"):
                if path.is_file():
                    found.add(path.resolve())
        for path in root.rglob("*.zip"):
            if path.is_file():
                found.add(path.resolve())

    current = db.get_db_path().resolve()
    filtered = [path for path in sorted(found) if path != current]
    return filtered
