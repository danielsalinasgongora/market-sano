# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixtures compartidas: app de prueba con SQLite temporal por test."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """Cliente HTTP con BD SQLite aislada en un directorio temporal."""
    settings = Settings(
        database_url=f"sqlite:///{tmp_path.as_posix()}/test.db",
        _env_file=None,  # ignorar .env local durante los tests
    )
    app = create_app(settings)
    return TestClient(app)
