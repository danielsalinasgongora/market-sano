# SPDX-License-Identifier: GPL-3.0-or-later
"""Endpoints REST de precios (spec §3.5): alta manual y consulta con trazabilidad."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.db import get_session
from app.models import ProductCatalog
from app.services.prices import PrecioResuelto, get_latest_price, registrar_precio_manual

router = APIRouter(tags=["precios"])


class PrecioManualIn(BaseModel):
    """Alta de precio manual (spec §3.5). El PPUM es obligatorio (spec §7.3)."""

    product_id: int
    store_id: str = Field(max_length=64)
    price_clp: int = Field(gt=0, description="Precio del artículo/pack en CLP")
    unit_price_clp: int = Field(gt=0, description="PPUM: precio por unidad de medida en CLP")
    is_promotion: bool = False


@router.post("/api/v1/prices", status_code=201)
def crear_precio_manual(
    datos: PrecioManualIn,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    """Registra un precio manual (`source=manual`, `confidence=high`)."""
    try:
        registrar_precio_manual(
            session,
            product_id=datos.product_id,
            store_id=datos.store_id,
            price_clp=datos.price_clp,
            unit_price_clp=datos.unit_price_clp,
            is_promotion=datos.is_promotion,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    resuelto = get_latest_price(
        session, product_id=datos.product_id, store_id=datos.store_id
    )
    assert resuelto is not None  # acabamos de crearlo
    return resuelto.a_dict()


@router.get("/api/v1/products/{product_id}/price")
def obtener_precio(
    product_id: int,
    store_id: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    """Último precio del producto en la cadena, con metadatos de trazabilidad.

    Si el producto no tiene precios registrados, `price` viene `null`
    (estado legítimo: aún no se ha consultado ninguna cadena).
    """
    if session.get(ProductCatalog, product_id) is None:
        raise HTTPException(status_code=404, detail=f"No existe el producto {product_id}.")

    ttl: int = request.app.state.settings.price_cache_ttl_hours
    resuelto: PrecioResuelto | None = get_latest_price(
        session, product_id=product_id, store_id=store_id, ttl_hours=ttl
    )
    if resuelto is None:
        return {"product_id": product_id, "store_id": store_id, "price": None}
    return {"product_id": product_id, "store_id": store_id, "price": resuelto.a_dict()}
