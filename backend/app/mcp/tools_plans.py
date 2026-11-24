# SPDX-License-Identifier: GPL-3.0-or-later
"""Tools MCP del planificador semanal (Task 16, spec §3.4).

Lectura (`get_meal_plan`, `get_budget_status`) exige scope `read`; escritura
(`create_meal_plan`, `set_meal_plan_entry`, `delete_meal_plan_entry`,
`estimate_meal_plan_cost`) exige `write_draft`.
"""

from datetime import date, timedelta
from typing import Annotated, Any

from fastmcp.exceptions import ToolError
from sqlmodel import Session

from app.mcp.db import mcp_engine
from app.mcp.permissions import (
    contexto_mcp,
    exigir_confirmacion,
    exigir_escritura,
    exigir_lectura,
)
from app.mcp.server import mcp
from app.services.planner import (
    PlanInvalido,
    PlanNoEncontrado,
    confirmar_plan,
    crear_plan,
    definir_entrada,
    eliminar_entrada,
    estado_presupuesto,
    estimar_costo_plan,
    listar_planes,
    normalizar_semana,
    obtener_plan,
    sugerir_plan,
)
from app.services.recipes import NoEncontrada
from app.settings import get_settings


def _accionable(fn: Any) -> Any:
    try:
        return fn()
    except (PlanInvalido, PlanNoEncontrado, NoEncontrada) as exc:
        raise ToolError(str(exc)) from exc


def _fecha(valor: str) -> date:
    try:
        return date.fromisoformat(valor.strip())
    except ValueError as exc:
        raise ToolError(
            f"Fecha inválida: {valor!r}. Usa formato ISO YYYY-MM-DD."
        ) from exc


@mcp.tool
def get_meal_plan(plan_id: Annotated[int, "ID del plan semanal"]) -> dict[str, Any]:
    """Plan con su semana, presupuesto, estado y entradas por día y slot."""
    with Session(mcp_engine()) as session:
        ctx = contexto_mcp(session)
        exigir_lectura(ctx)
        return _accionable(lambda: obtener_plan(session, ctx.hogar.id, plan_id))


@mcp.tool
def list_meal_plans(
    week_start: Annotated[
        str | None, "Lunes ISO (YYYY-MM-DD) para filtrar; omitir lista todos"
    ] = None,
) -> list[dict[str, Any]]:
    """Planes del hogar ordenados del más reciente al más antiguo."""
    with Session(mcp_engine()) as session:
        ctx = contexto_mcp(session)
        exigir_lectura(ctx)
        dia = _fecha(week_start) if week_start else None
        return _accionable(lambda: listar_planes(session, ctx.hogar.id, week_start=dia))


@mcp.tool
def create_meal_plan(
    week_start: Annotated[str, "Fecha ISO dentro de la semana (se normaliza al lunes)"],
    budget_clp: Annotated[int, "Presupuesto semanal en CLP (>0)"],
    dry_run: Annotated[bool, "true (defecto): solo vista previa; false: guarda"] = True,
) -> dict[str, Any]:
    """Crea el plan draft de una semana (uno por hogar y semana).

    Con dry_run=true valida y devuelve la vista previa sin escribir; repite con
    dry_run=false solo si el usuario confirma.
    """
    with Session(mcp_engine()) as session:
        ctx = contexto_mcp(session)
        exigir_escritura(ctx)
        dia = _fecha(week_start)

        def accion() -> dict[str, Any]:
            if budget_clp <= 0:
                raise PlanInvalido("budget_clp debe ser mayor que 0.")
            lunes = normalizar_semana(dia)
            existentes = listar_planes(session, ctx.hogar.id, week_start=lunes)
            if existentes:
                raise PlanInvalido(
                    f"Ya existe el plan {existentes[0]['plan_id']} para la semana del "
                    f"{lunes.isoformat()}. Edítalo en vez de crear otro."
                )
            if dry_run:
                return {
                    "dry_run": True,
                    "week_start": lunes.isoformat(),
                    "week_end": (lunes + timedelta(days=6)).isoformat(),
                    "budget_clp": budget_clp,
                }
            return crear_plan(
                session,
                ctx.hogar.id,
                week_start=lunes,
                budget_clp=budget_clp,
                created_by=ctx.usuario.id,
            )

        return _accionable(accion)


@mcp.tool
def set_meal_plan_entry(
    plan_id: Annotated[int, "ID del plan draft"],
    date: Annotated[str, "Día ISO (YYYY-MM-DD) dentro de la semana del plan"],
    meal_slot: Annotated[str, "desayuno | almuerzo | cena | snack"],
    recipe_id: Annotated[int | None, "Receta a servir; omitir para noche libre"] = None,
    servings_multiplier: Annotated[float, "Multiplicador de porciones (1.0 = base)"] = 1.0,
    label: Annotated[str | None, "Etiqueta; obligatoria en la noche libre"] = None,
    estimated_cost_clp: Annotated[
        int | None, "Costo estimado CLP; obligatorio en la noche libre"
    ] = None,
) -> dict[str, Any]:
    """Crea o reemplaza la entrada del día+slot (upsert). Sin receta = noche
    libre (sobras o llevar), que descuenta `estimated_cost_clp` del presupuesto."""
    with Session(mcp_engine()) as session:
        ctx = contexto_mcp(session)
        exigir_escritura(ctx)
        dia = _fecha(date)
        return _accionable(
            lambda: definir_entrada(
                session,
                ctx.hogar.id,
                plan_id,
                fecha=dia,
                meal_slot=meal_slot,
                recipe_id=recipe_id,
                servings_multiplier=servings_multiplier,
                label=label,
                estimated_cost_clp=estimated_cost_clp,
            )
        )


@mcp.tool
def delete_meal_plan_entry(
    plan_id: Annotated[int, "ID del plan draft"],
    entry_id: Annotated[int, "ID de la entrada a quitar"],
) -> dict[str, Any]:
    """Quita una entrada del plan y devuelve el plan actualizado."""
    with Session(mcp_engine()) as session:
        ctx = contexto_mcp(session)
        exigir_escritura(ctx)
        return _accionable(
            lambda: eliminar_entrada(session, ctx.hogar.id, plan_id, entry_id)
        )


@mcp.tool
def estimate_meal_plan_cost(
    plan_id: Annotated[int, "ID del plan"],
    store_ids: Annotated[
        list[str] | None, 'Cadenas a comparar, ej. ["jumbo", "santaisabel"]'
    ] = None,
) -> dict[str, Any]:
    """Estima el costo total por cadena con el último precio de cada
    ingrediente y guarda un snapshot histórico por cadena."""
    with Session(mcp_engine()) as session:
        ctx = contexto_mcp(session)
        exigir_escritura(ctx)
        return _accionable(
            lambda: estimar_costo_plan(
                session, ctx.hogar.id, plan_id, store_ids=store_ids
            )
        )


@mcp.tool
def get_budget_status(
    plan_id: Annotated[int, "ID del plan"],
    store_id: Annotated[str | None, "Cadena para el cálculo; omitir usa la del hogar"] = None,
) -> dict[str, Any]:
    """`budget_clp`, `estimated_clp` y `variance_clp` del plan (negativo =
    excedido), con el porcentaje de uso y qué productos quedaron sin precio."""
    with Session(mcp_engine()) as session:
        ctx = contexto_mcp(session)
        exigir_lectura(ctx)
        return _accionable(
            lambda: estado_presupuesto(
                session, ctx.hogar.id, plan_id, store_id=store_id
            )
        )


@mcp.tool
def suggest_meal_plan(
    week_start: Annotated[str, "Fecha ISO dentro de la semana (se normaliza al lunes)"],
    budget_clp: Annotated[int, "Presupuesto semanal en CLP (>0)"],
    store_id: Annotated[str | None, "Cadena para costos; omitir usa la del hogar"] = None,
    variety_weeks: Annotated[
        int | None, "Semanas sin repetir receta; omitir usa la configuración"
    ] = None,
    free_nights: Annotated[int, "Cuántas de las 7 cenas son noche libre (0-6)"] = 1,
    free_night_cost_clp: Annotated[
        int | None, "Monto CLP por noche libre; omitir usa la configuración"
    ] = None,
    dry_run: Annotated[bool, "true (defecto): solo vista previa; false: guarda"] = True,
) -> dict[str, Any]:
    """Sugiere 7 cenas variadas dentro del presupuesto, sin repetir recetas de
    las últimas semanas. Las últimas N cenas son noche libre con costo
    explícito. Con dry_run=false crea el plan draft con esas entradas."""
    with Session(mcp_engine()) as session:
        ctx = contexto_mcp(session)
        exigir_escritura(ctx)
        dia = _fecha(week_start)
        settings = get_settings()
        return _accionable(
            lambda: sugerir_plan(
                session,
                ctx.hogar.id,
                week_start=dia,
                budget_clp=budget_clp,
                store_id=store_id,
                variety_weeks=(
                    settings.plan_variety_weeks
                    if variety_weeks is None
                    else variety_weeks
                ),
                free_nights=free_nights,
                free_night_cost_clp=(
                    settings.free_night_cost_clp
                    if free_night_cost_clp is None
                    else free_night_cost_clp
                ),
                dry_run=dry_run,
                created_by=ctx.usuario.id,
            )
        )


@mcp.tool
def confirm_meal_plan(plan_id: Annotated[int, "ID del plan draft"]) -> dict[str, Any]:
    """Confirma el plan y lo congela. Exige un token MCP con scope `confirm`
    (los tokens de solo lectura/borrador no alcanzan) y que el plan esté
    dentro del presupuesto con precios completos."""
    with Session(mcp_engine()) as session:
        ctx = contexto_mcp(session)
        exigir_confirmacion(ctx)
        return _accionable(lambda: confirmar_plan(session, ctx.hogar.id, plan_id))
