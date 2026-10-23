from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from bis_core.db import close_db, get_db

APP_DB = Path(__file__).resolve().parents[2] / "data" / "app.db"


@pytest.fixture
def app_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[sqlite3.Connection]:
    """`get_db()` pointed at a consistent COPY of data/app.db (the real file is never written)."""
    if not APP_DB.exists():
        pytest.skip("data/app.db not present")
    copy = tmp_path / "app.db"
    src = sqlite3.connect(f"file:{APP_DB}?mode=ro", uri=True)
    dst = sqlite3.connect(copy)
    src.backup(dst)
    src.close()
    dst.close()
    close_db()
    monkeypatch.setenv("DB_PATH", str(copy))
    yield get_db()
    close_db()
