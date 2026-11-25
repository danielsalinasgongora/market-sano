# SPDX-License-Identifier: GPL-3.0-or-later
"""API de despensa y gastos (spec §3.3, §3.6).

Endpoints REST para gestión de inventario y registro de gastos.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.api.deps import contexto, requiere_escritura
from app.db import get_session
from app.models.enums import MovementReason
from app.services.expenses import (
    get_budget_variance,
    get_spending_summary,
    obtener_gastos,
    registrar_gasto,
)
from app.services.households import ContextoHogar
from app.services.pantry import (
    ajustar_cantidad,
    get_pantry_shortfall,
    obtener_despensa,
    obtener_status,
)

router = APIRouter(prefix="/api/v1", tags=["despensa"])


# === Pantry ===

class AjustarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: int = Field(description="ID del producto")
    delta: float = Field(description="Cambio de cantidad (positivo/negativo)")
    reason: MovementReason = Field(description="Motivo del ajuste")
    reference_id: str | None = None


class ShortfallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipe_id: int = Field(description="ID de la receta")
    servings_multiplier: float = Field(default=1.0, gt=0)


@router.post("/pantry/items")
def ajustar(
    datos: AjustarRequest,
    session: Annotated[Session, Depends(get_session)],
    ctx: Annotated[ContextoHogar, Depends(requiere_escritura)],
) -> dict:
    """Ajusta cantidad de un ítem y registra el movimiento."""
    return ajustar_cantidad(
        session,
        ctx.hogar.id,
        datos.product_id,
        datos.delta,
        datos.reason,
        datos.reference_id,
    )


@router.get("/pantry/items")
def listar(
    session: Annotated[Session, Depends(get_session)],
    ctx: Annotated[ContextoHogar, Depends(contexto)],
    location: str | None = Query(None),
) -> list[dict]:
    """Lista items de despensa filtrados por ubicación opcional."""
    return obtener_despensa(session, ctx.hogar.id, location)


@router.get("/pantry/status")
def status(
    session: Annotated[Session, Depends(get_session)],
    ctx: Annotated[ContextoHogar, Depends(contexto)],
    expiring_within_days: Annotated[int, Query(ge=1, le=30)] = 3,
) -> dict:
    """Estado de la despensa con items a vencer."""
    return obtener_status(session, ctx.hogar.id, expiring_within_days)


@router.post("/pantry/shortfall")
def shortfall(
    datos: ShortfallRequest,
    session: Annotated[Session, Depends(get_session)],
    ctx: Annotated[ContextoHogar, Depends(contexto)],
) -> list[dict]:
    """Calcula qué ingredientes faltan para una receta."""
    return get_pantry_shortfall(
        session, ctx.hogar.id, datos.recipe_id, datos.servings_multiplier
    )


# === Expenses ===

@router.post("/expenses")
def registrar(
    amount_clp: Annotated[int, Field(gt=0, description="Monto en CLP")],
    session: Annotated[Session, Depends(get_session)],
    ctx: Annotated[ContextoHogar, Depends(requiere_escritura)],
) -> dict:
    """Registra un gasto real del hogar."""
    return registrar_gasto(session, ctx.hogar.id, amount_clp)


@router.get("/expenses")
def listar_expenses(
    session: Annotated[Session, Depends(get_session)],
    ctx: Annotated[ContextoHogar, Depends(contexto)],
    start_date: Annotated[date | None, Query(description="Filtrar desde fecha")] = None,
) -> list[dict]:
    """Lista gastos del hogar, opcionalmente desde una fecha."""
    return obtener_gastos(session, ctx.hogar.id, start_date)


@router.get("/expenses/summary")
def resumen(
    session: Annotated[Session, Depends(get_session)],
    ctx: Annotated[ContextoHogar, Depends(contexto)],
    start_date: date = ...,
    end_date: Annotated[date | None, Query(description="Filtrar hasta fecha")] = None,
    group_by: Annotated[str, Query(description="Agrupar por 'category' o 'store'")] = "category",
) -> dict:
    """Resumen de gastos agrupados."""
    return get_spending_summary(session, ctx.hogar.id, start_date, end_date, group_by)


@router.get("/expenses/variance")
def varianza(
    session: Annotated[Session, Depends(get_session)],
    ctx: Annotated[ContextoHogar, Depends(contexto)],
    start_date: date = ...,
    end_date: Annotated[date | None, Query()] = None,
) -> dict:
    """Compara gastos reales vs presupuesto planificado."""
    if end_date is None:
        end_date = date.today()
    return get_budget_variance(session, ctx.hogar.id, start_date, end_date)