from __future__ import annotations

from pathlib import Path

import pytest

from app import db


@pytest.fixture(autouse=True)
def isolated_database(tmp_path: Path) -> None:
    db.configure_database(tmp_path / "test_app.db")
    db.init_db()
