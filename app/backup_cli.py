from __future__ import annotations

import argparse
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from app import db


REQUIRED_TABLES = {
    "schema_migrations",
    "settings",
    "incomes",
    "expenses",
    "accounts",
    "fiscal_periods",
    "vouchers",
    "voucher_lines",
    "bilag_files",
    "audit_log",
    "users",
}


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def create_backup(*, include_reports: bool = True) -> Path:
    db.init_db()
    db.ensure_data_dirs()
    backup_name = f"backup_{_timestamp()}.zip"
    output_path = db.BACKUPS_DIR / backup_name
    with zipfile.ZipFile(output_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        db_path = db.get_db_path()
        if db_path.exists():
            archive.write(db_path, arcname="db/app.db")

        if db.ATTACHMENTS_DIR.exists():
            for path in db.ATTACHMENTS_DIR.rglob("*"):
                if path.is_file():
                    arc_name = Path("attachments") / path.relative_to(db.ATTACHMENTS_DIR)
                    archive.write(path, arcname=str(arc_name))

        if include_reports and db.REPORTS_DIR.exists():
            for path in db.REPORTS_DIR.rglob("*"):
                if path.is_file():
                    arc_name = Path("reports") / path.relative_to(db.REPORTS_DIR)
                    archive.write(path, arcname=str(arc_name))
    return output_path


def verify_backup_archive(archive_path: Path) -> dict[str, int]:
    if not archive_path.exists():
        raise FileNotFoundError(f"Fant ikke backupfil: {archive_path}")

    with tempfile.TemporaryDirectory(prefix="regnskap_backup_verify_") as tmp_dir:
        tmp_root = Path(tmp_dir)
        with zipfile.ZipFile(archive_path, mode="r") as archive:
            archive.extractall(tmp_root)
        db_file = tmp_root / "db" / "app.db"
        if not db_file.exists():
            raise RuntimeError("Backup mangler db/app.db")

        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
        try:
            tables = {
                row["name"]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            missing = REQUIRED_TABLES - tables
            if missing:
                raise RuntimeError(f"Backup mangler tabeller: {', '.join(sorted(missing))}")
            counts = {
                "vouchers": int(conn.execute("SELECT COUNT(*) FROM vouchers").fetchone()[0]),
                "voucher_lines": int(conn.execute("SELECT COUNT(*) FROM voucher_lines").fetchone()[0]),
                "bilag_files": int(conn.execute("SELECT COUNT(*) FROM bilag_files").fetchone()[0]),
                "legacy_incomes": int(conn.execute("SELECT COUNT(*) FROM incomes").fetchone()[0]),
                "legacy_expenses": int(conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]),
            }
            return counts
        finally:
            conn.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backup/restore-verifisering for mini-regnskap")
    sub = parser.add_subparsers(dest="command", required=True)

    backup_cmd = sub.add_parser("backup", help="Lag backup zip")
    backup_cmd.add_argument("--no-reports", action="store_true", help="Ikke ta med data/reports")

    verify_cmd = sub.add_parser("verify", help="Verifiser backup zip")
    verify_cmd.add_argument("--archive", required=True, help="Path til backup zip")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command == "backup":
        output = create_backup(include_reports=not bool(args.no_reports))
        print(f"Backup opprettet: {output}")
        return
    if args.command == "verify":
        archive_path = Path(args.archive)
        counts = verify_backup_archive(archive_path)
        print(f"Backup OK: {archive_path}")
        for key, value in counts.items():
            print(f"{key}={value}")
        return


if __name__ == "__main__":
    main()

