# SPDX-License-Identifier: GPL-3.0-or-later
"""API de Market Sano — fábrica de la aplicación FastAPI.

Producción: `uvicorn app.main:app`. Tests: `create_app(settings)`.
"""

from fastapi import FastAPI

from app.api import health, prices, products
from app.db import get_engine
from app.settings import Settings, get_settings

API_DESCRIPTION = (
    "Planificador de comidas local-first y MCP-first, con precios reales "
    "del retail chileno. 100% open-source (GPL-3.0-or-later), sin telemetría."
)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Fábrica de la app; acepta settings inyectables para tests."""
    settings = settings or get_settings()

    app = FastAPI(
        title="Market Sano API",
        description=API_DESCRIPTION,
        version="0.1.0",
        license_info={
            "name": "GPL-3.0-or-later",
            "url": "https://www.gnu.org/licenses/gpl-3.0.html",
        },
    )
    app.state.settings = settings
    app.state.engine = get_engine(settings.database_url)

    app.include_router(health.router)
    app.include_router(prices.router)
    app.include_router(products.router)

    @app.get("/", tags=["salud"])
    def root() -> dict[str, str]:
        return {"app": "Market Sano API", "version": "0.1.0", "docs": "/docs"}

    return app


app = create_app()
