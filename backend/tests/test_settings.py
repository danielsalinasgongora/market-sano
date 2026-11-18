# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests de configuración por entorno."""

import pytest

from app.settings import Settings


def test_defaults_son_local_first() -> None:
    """Sin entorno ni .env: SQLite, sin login, sin IA, sin MQTT (spec §0)."""
    settings = Settings(_env_file=None)
    assert settings.database_url.startswith("sqlite")
    assert settings.auth_mode == "none"
    assert settings.ai_provider == "none"
    assert settings.mqtt_enabled is False
    assert settings.supermercados_enabled is False
    assert settings.price_cache_ttl_hours == 12


def test_variables_de_entorno_sobrescriben(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://marketsano:x@db:5432/marketsano")
    monkeypatch.setenv("AUTH_MODE", "local")
    settings = Settings(_env_file=None)
    assert settings.database_url == "postgresql://marketsano:x@db:5432/marketsano"
    assert settings.auth_mode == "local"
