# SPDX-License-Identifier: GPL-3.0-or-later
"""Configuración de Market Sano por entorno.

Lee variables de entorno (docker compose las inyecta) y, si existe, un
archivo `.env` local. Nunca se persisten secretos en la base de datos.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── Base de datos ─────────────────────────────────────────
    # SQLite por defecto (perfil minimal); Postgres en perfil standard.
    database_url: str = "sqlite:///./data/app.db"

    # ── Autenticación ─────────────────────────────────────────
    # none  → sin login: hogar por defecto, owner implícito.
    # local → registro email + Argon2id, roles e invitaciones (multi-usuario).
    auth_mode: str = "none"

    # ── IA (opcional; el sistema es 100% funcional sin IA) ────
    ai_provider: str = "none"
    ai_api_key: str = ""
    ai_model: str = ""
    ai_base_url: str = ""

    # ── MCP ───────────────────────────────────────────────────
    mcp_transport: str = "stdio"  # stdio | http
    mcp_http_port: int = 8765

    # ── Home Assistant (opcional) ─────────────────────────────
    mqtt_enabled: bool = False
    mqtt_broker_url: str = "mqtt://mqtt:1883"

    # ── Conector de supermercados (opcional, 100% local) ──────
    supermercados_enabled: bool = False
    # Comando que lanza el conector MCP por stdio (JSON en la variable de entorno).
    # La imagen Docker lo trae instalado en /opt (ver docker/Dockerfile).
    supermercados_command: list[str] = ["npx", "-y", "mcp-supermercados-cl@1.4.9"]
    supermercados_timeout_s: float = 30.0

    # ── Capa de precios ───────────────────────────────────────
    price_cache_ttl_hours: int = 12


def get_settings() -> Settings:
    """Settings frescos por llamada (barato y fácil de sobrescribir en tests)."""
    return Settings()
