# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixtures compartidas: app de prueba con SQLite temporal + BD migrada desde cero."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session

from app.db import get_engine
from app.main import create_app
from app.settings import Settings

BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """Cliente HTTP con BD SQLite aislada en un directorio temporal."""
    settings = Settings(
        database_url=f"sqlite:///{tmp_path.as_posix()}/test.db",
        _env_file=None,  # ignorar .env local durante los tests
    )
    app = create_app(settings)
    return TestClient(app)


def alembic_config_for(db_url: str) -> Config:
    """Config de Alembic apuntando a una BD explícita (tests y verificaciones)."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


@pytest.fixture()
def migrated_engine(tmp_path: Path) -> Engine:
    """Motor sobre una BD migrada desde cero: valida la migración real, no create_all."""
    db_url = f"sqlite:///{tmp_path.as_posix()}/db.sqlite3"
    command.upgrade(alembic_config_for(db_url), "head")
    return get_engine(db_url)


@pytest.fixture()
def engine_sembrado(tmp_path: Path) -> Engine:
    """Motor con datos semilla (products, recipes, pantry, etc.)."""
    from app.db import get_engine
    from app.seed import seed

    db_url = f"sqlite:///{tmp_path.as_posix()}/seeded.db"
    command.upgrade(alembic_config_for(db_url), "head")
    engine = get_engine(db_url)
    with Session(engine) as session:
        seed(session)
    return engine
