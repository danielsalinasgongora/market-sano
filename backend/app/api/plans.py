# SPDX-License-Identifier: GPL-3.0-or-later
"""Endpoints REST de planificación semanal (spec §3.4, Task 16)."""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.deps import (
    contexto,
    requiere_escritura,
    requiere_scope,
    settings_de_app,
)
from app.db import get_session
from app.services.households import ContextoHogar
from app.services.planner import (
    PlanInvalido,
    PlanNoEncontrado,
    confirmar_plan,
    crear_plan,
    estado_presupuesto,
    estimar_costo_plan,
    listar_planes,
    obtener_plan,
    sugerir_plan,
)
from app.services.planner import (
    definir_entrada as definir_entrada_plan,
)
from app.services.planner import (
    eliminar_entrada as eliminar_entrada_plan,
)
from app.services.recipes import NoEncontrada
from app.settings import Settings

router = APIRouter(prefix="/api/v1/plans", tags=["planes"])
SesionDep = Annotated[Session, Depends(get_session)]


class PlanIn(BaseModel):
    week_start: date
    budget_clp: int = Field(gt=0, description="Presupuesto semanal en CLP")


class EntradaIn(BaseModel):
    date: date
    meal_slot: str = Field(description="desayuno | almuerzo | cena | snack")
    recipe_id: int | None = None
    servings_multiplier: float = Field(default=1.0, gt=0)
    label: str | None = Field(default=None, max_length=120)
    estimated_cost_clp: int | None = Field(default=None, ge=0)


class EstimacionIn(BaseModel):
    store_ids: list[str] | None = None


class SugerenciaIn(BaseModel):
    week_start: date
    budget_clp: int = Field(gt=0)
    store_id: str | None = None
    variety_weeks: int | None = Field(default=None, ge=0, le=52)
    free_nights: int = Field(default=1, ge=0, le=6)
    free_night_cost_clp: int | None = Field(default=None, ge=0)
    dry_run: bool = True


def _errores(fn: Any) -> Any:
    try:
        return fn()
    except (PlanNoEncontrado, NoEncontrada) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PlanInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("", status_code=201)
def crear(
    datos: PlanIn,
    session: SesionDep,
    ctx: Annotated[ContextoHogar, Depends(requiere_escritura)],
) -> dict[str, Any]:
    """Crea el plan draft de la semana (lunes como inicio)."""
    return _errores(
        lambda: crear_plan(
            session,
            ctx.hogar.id,
            week_start=datos.week_start,
            budget_clp=datos.budget_clp,
            created_by=ctx.usuario.id,
        )
    )


@router.get("")
def listar(
    session: SesionDep,
    ctx: Annotated[ContextoHogar, Depends(contexto)],
    week_start: Annotated[date | None, Query()] = None,
) -> list[dict[str, Any]]:
    """Planes del hogar, opcionalmente filtrados por semana."""
    return listar_planes(session, ctx.hogar.id, week_start=week_start)


@router.post("/suggest")
def sugerir(
    datos: SugerenciaIn,
    session: SesionDep,
    ctx: Annotated[ContextoHogar, Depends(requiere_escritura)],
    settings: Annotated[Settings, Depends(settings_de_app)],
) -> dict[str, Any]:
    """Sugiere un plan de 7 cenas dentro del presupuesto y con variedad."""
    return _errores(
        lambda: sugerir_plan(
            session,
            ctx.hogar.id,
            week_start=datos.week_start,
            budget_clp=datos.budget_clp,
            store_id=datos.store_id,
            variety_weeks=(
                settings.plan_variety_weeks
                if datos.variety_weeks is None
                else datos.variety_weeks
            ),
            free_nights=datos.free_nights,
            free_night_cost_clp=(
                settings.free_night_cost_clp
                if datos.free_night_cost_clp is None
                else datos.free_night_cost_clp
            ),
            dry_run=datos.dry_run,
            created_by=ctx.usuario.id,
        )
    )


@router.get("/{plan_id}")
def obtener(
    plan_id: int, session: SesionDep, ctx: Annotated[ContextoHogar, Depends(contexto)]
) -> dict[str, Any]:
    """Plan con sus entradas."""
    return _errores(lambda: obtener_plan(session, ctx.hogar.id, plan_id))


@router.put("/{plan_id}/entries")
def definir_entrada(
    plan_id: int,
    datos: EntradaIn,
    session: SesionDep,
    ctx: Annotated[ContextoHogar, Depends(requiere_escritura)],
) -> dict[str, Any]:
    """Crea o reemplaza la entrada del día+slot (upsert)."""
    return _errores(
        lambda: definir_entrada_plan(
            session,
            ctx.hogar.id,
            plan_id,
            fecha=datos.date,
            meal_slot=datos.meal_slot,
            recipe_id=datos.recipe_id,
            servings_multiplier=datos.servings_multiplier,
            label=datos.label,
            estimated_cost_clp=datos.estimated_cost_clp,
        )
    )


@router.delete("/{plan_id}/entries/{entry_id}", status_code=204)
def borrar_entrada(
    plan_id: int,
    entry_id: int,
    session: SesionDep,
    ctx: Annotated[ContextoHogar, Depends(requiere_escritura)],
) -> Response:
    """Quita una entrada del plan draft."""
    _errores(lambda: eliminar_entrada_plan(session, ctx.hogar.id, plan_id, entry_id))
    return Response(status_code=204)


@router.post("/{plan_id}/estimate")
def estimar(
    plan_id: int,
    datos: EstimacionIn,
    session: SesionDep,
    ctx: Annotated[ContextoHogar, Depends(requiere_escritura)],
) -> dict[str, Any]:
    """Estima el costo por cadena y guarda un snapshot por cada una."""
    return _errores(
        lambda: estimar_costo_plan(
            session, ctx.hogar.id, plan_id, store_ids=datos.store_ids
        )
    )


@router.get("/{plan_id}/budget")
def presupuesto(
    plan_id: int,
    session: SesionDep,
    ctx: Annotated[ContextoHogar, Depends(contexto)],
    store_id: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    """Presupuesto vs estimado (`variance_clp` negativo = excedido)."""
    return _errores(
        lambda: estado_presupuesto(session, ctx.hogar.id, plan_id, store_id=store_id)
    )


@router.post("/{plan_id}/confirm")
def confirmar(
    plan_id: int,
    session: SesionDep,
    ctx: Annotated[ContextoHogar, Depends(requiere_escritura)],
    _scope: Annotated[None, Depends(requiere_scope("confirm"))],
) -> dict[str, Any]:
    """Confirma el plan (requiere token con scope `confirm`) y lo congela."""
    return _errores(lambda: confirmar_plan(session, ctx.hogar.id, plan_id))
