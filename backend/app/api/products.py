# SPDX-License-Identifier: GPL-3.0-or-later
"""Catálogo abierto (Task 9b): buscar en una cadena y dar de alta productos."""

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.connectors.supermercados_cl import ErrorConector, buscar_productos
from app.db import get_session
from app.services.catalogo_abierto import AltaInvalida, alta_desde_cadena

router = APIRouter(tags=["catálogo"])


class AltaDesdeCadenaIn(BaseModel):
    """Campos tal como los devuelve la búsqueda en la cadena."""

    store_id: str = Field(max_length=64)
    store_url: str = Field(max_length=500)
    sku: str | None = Field(default=None, max_length=64)
    store_product_name: str = Field(max_length=300)
    unit: str = Field(description="Unidad del PPUM del resultado: kg | lt | un")
    canonical_name: str = Field(max_length=200, description="Nombre en tu catálogo")
    category: str = Field(default="otros", max_length=100)
    product_id: int | None = Field(default=None, description="Vincular a un producto existente")


@router.get("/api/v1/stores/{store_id}/products")
def buscar_en_cadena(
    store_id: str,
    request: Request,
    query: Annotated[str, Query(min_length=1)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> dict[str, Any]:
    """Busca en la cadena vía el conector (no escribe nada)."""
    try:
        productos = asyncio.run(
            buscar_productos(request.app.state.settings, store_id, query, limit)
        )
    except ErrorConector as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"store_id": store_id, "query": query, "products": productos}


@router.post("/api/v1/products/from-store")
def alta_producto_desde_cadena(
    datos: AltaDesdeCadenaIn,
    session: Annotated[Session, Depends(get_session)],
    dry_run: bool = True,
) -> dict[str, Any]:
    """Crea/vincula el producto y fija su match. `dry_run=true` (defecto) solo previsualiza."""
    try:
        return alta_desde_cadena(session, dry_run=dry_run, **datos.model_dump())
    except AltaInvalida as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
