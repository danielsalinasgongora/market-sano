# SPDX-License-Identifier: GPL-3.0-or-later
"""API de listas de compras (Task 20, spec §3.5).

Endpoints REST para generación, visualización y comparación de listas de compras.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.api.deps import contexto, requiere_escritura
from app.db import get_session
from app.services.households import ContextoHogar
from app.services.shopping import (
    ShoppingError,
    comparar_basket_across_stores,
    generar_lista,
    obtener_lista,
)

router = APIRouter(prefix="/api/v1", tags=["listas"])


class GenerarListaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: int | None = Field(None, description="ID del plan")
    store_ids: list[str] | None = Field(None, description="Cadenas a incluir")
    name: str = Field(default="Lista de compras", max_length=120)


@router.post("/lists")
def generar(
    datos: GenerarListaRequest,
    session: Annotated[Session, Depends(get_session)],
    ctx: Annotated[ContextoHogar, Depends(requiere_escritura)],
) -> dict:
    """Genera lista de compras."""
    return generar_lista(
        session,
        ctx.hogar.id,
        datos.plan_id,
        datos.store_ids,
        datos.name,
    )


@router.get("/lists")
def listar_listas(
    session: Annotated[Session, Depends(get_session)],
    ctx: Annotated[ContextoHogar, Depends(contexto)],
) -> list[dict]:
    """Lista de compras activas del hogar."""
    from sqlmodel import select
    from app.models import ShoppingList
    listas = session.exec(
        select(ShoppingList)
        .where(ShoppingList.household_id == ctx.hogar.id)
        .where(ShoppingList.status == "active")
        .order_by(ShoppingList.created_at.desc())
    ).all()
    return [
        {
            "list_id": l.id,
            "name": l.name,
            "status": l.status.value,
            "created_at": l.created_at.isoformat(),
        }
        for l in listas
    ]


@router.get("/lists/{list_id}")
def obtener(
    list_id: int,
    session: Annotated[Session, Depends(get_session)],
    ctx: Annotated[ContextoHogar, Depends(contexto)],
    group_by: Annotated[str, Query(default="aisle")] = "aisle",
) -> dict:
    """Detalles de una lista de compras."""
    return obtener_lista(session, ctx.hogar.id, list_id, group_by)


@router.get("/lists/{list_id}/compare")
def comparar(
    list_id: int,
    session: Annotated[Session, Depends(get_session)],
    ctx: Annotated[ContextoHogar, Depends(contexto)],
    threshold_pct: Annotated[float, Query(ge=0, le=1)] = 0.10,
) -> dict:
    """Compara costo de la lista por cadena."""
    return comparar_basket_across_stores(
        session, ctx.hogar.id, list_id, threshold_pct
    )


@router.get("/shopping-lists/active")
def lista_activa(
    session: Annotated[Session, Depends(get_session)],
    ctx: Annotated[ContextoHogar, Depends(contexto)],
) -> dict:
    """Lista de compras activa del hogar."""
    from sqlmodel import select
    from app.models import ShoppingList
    lista = session.exec(
        select(ShoppingList)
        .where(ShoppingList.household_id == ctx.hogar.id)
        .where(ShoppingList.status == "active")
        .order_by(ShoppingList.created_at.desc())
        .limit(1)
    ).first()
    if lista is None:
        return {"list_id": None, "name": None, "items": []}
    return obtener_lista(session, ctx.hogar.id, lista.id)