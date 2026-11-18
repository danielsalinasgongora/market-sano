# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests del motor de base de datos."""

from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session

from app.db import get_engine


def test_get_engine_crea_directorio_padre(tmp_path: Path) -> None:
    """Primer arranque sin directorio de datos: no debe fallar (regresión)."""
    db_file = tmp_path / "anidado" / "dir" / "app.db"
    engine = get_engine(f"sqlite:///{db_file.as_posix()}")

    with Session(engine) as session:
        session.execute(text("SELECT 1"))

    assert db_file.exists()


def test_get_engine_sqlite_wal(tmp_path: Path) -> None:
    """SQLite debe quedar en modo WAL (spec: contenedor local-first)."""
    db_file = tmp_path / "app.db"
    engine = get_engine(f"sqlite:///{db_file.as_posix()}")

    with Session(engine) as session:
        mode = session.execute(text("PRAGMA journal_mode")).scalar_one()

    assert str(mode).lower() == "wal"
