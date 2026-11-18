# SPDX-License-Identifier: GPL-3.0-or-later
"""Motor de BD del proceso MCP.

El servidor MCP corre como proceso separado de la API (spec §9.3) y abre
sus propias sesiones contra la misma base. Las tools nunca construyen
motores por llamada: usan este proveedor lazy y cacheado.
"""

from sqlalchemy import Engine

from app.db import get_engine
from app.settings import get_settings

_engine: Engine | None = None


def mcp_engine() -> Engine:
    """Motor para las tools (lazy, cacheado por proceso)."""
    global _engine
    if _engine is None:
        _engine = get_engine(get_settings().database_url)
    return _engine


def set_mcp_engine(engine: Engine | None) -> None:
    """Inyección explícita para tests; con None restaura el comportamiento por defecto."""
    global _engine
    _engine = engine
