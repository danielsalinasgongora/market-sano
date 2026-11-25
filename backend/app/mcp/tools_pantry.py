# SPDX-License-Identifier: GPL-3.0-or-later
"""Tools MCP de despensa y gastos (Task 19, Task 22, spec §3.3, §3.6).

Con `AUTH_MODE=none` el invocador actúa como owner implícito del hogar por
defecto; los permisos por token/rol de MCP llegan en T15.
"""

from datetime import date
from typing import Annotated, Any

from fastmcp.exceptions import ToolError
from sqlmodel import Session

from app.mcp.db import mcp_engine
from app.mcp.permissions import (
    contexto_mcp,
    exigir_escritura,
    exigir_lectura,
)
from app.mcp.server import mcp
from app.models.enums import MovementReason
from app.services.expenses import (
    ExpenseError,
    get_budget_variance,
    get_spending_summary,
    registrar_gasto,
)
from app.services.pantry import (
    PantryError,
    ajustar_cantidad,
    get_pantry_shortfall,
    obtener_status,
)
from app.services.shopping import (
    ShoppingError,
    comparar_basket_across_stores,
    generar_lista,
    obtener_lista,
)


def _accionable(fn: Any) -> Any:
    try:
        return fn()
    except (PantryError, ExpenseError, ShoppingError) as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool
def get_pantry_status(
    expiring_within_days: Annotated[
        int | None, "Items a vencer en N días; omitir usa 3"
    ] = None,
) -> dict[str, Any]:
    """Estado de la despensa con items a vencer."""
    with Session(mcp_engine()) as session:
        ctx = contexto_mcp(session)
        exigir_lectura(ctx)
        return _accionable(
            lambda: obtener_status(
                session, ctx.hogar.id, expiring_within_days or 3
            )
        )


@mcp.tool
def adjust_pantry_item(
    product_id: Annotated[int, "ID del producto"],
    delta: Annotated[float, "Cambio de cantidad (positivo/negativo)"],
    reason: Annotated[
        str, "Motivo: purchase, recipe_consumption, manual_adjustment, spoilage"
    ],
    reference_id: Annotated[str | None, "ID referencia opcinal"] = None,
) -> dict[str, Any]:
    """Ajusta cantidad de un ítem y registra el movimiento."""
    with Session(mcp_engine()) as session:
        ctx = contexto_mcp(session)
        exigir_escritura(ctx)
        try:
            reason_enum = MovementReason(reason.lower())
        except ValueError as exc:
            raise ToolError(
                f"Motivo inválido: {reason}. Usa: purchase, recipe_consumption, "
                "manual_adjustment o spoilage."
            ) from exc
        return _accionable(
            lambda: ajustar_cantidad(
                session, ctx.hogar.id, product_id, delta, reason_enum, reference_id
            )
        )


@mcp.tool
def get_pantry_shortfall_tool(
    recipe_id: Annotated[int, "ID de la receta"],
    servings_multiplier: Annotated[float, "Multiplicador de porciones"] = 1.0,
) -> list[dict[str, Any]]:
    """Calcula qué ingredientes faltan para una receta."""
    with Session(mcp_engine()) as session:
        ctx = contexto_mcp(session)
        exigir_lectura(ctx)
        return _accionable(
            lambda: get_pantry_shortfall(
                session, ctx.hogar.id, recipe_id, servings_multiplier
            )
        )


@mcp.tool
def record_expense(
    amount_clp: Annotated[int, "Monto en CLP (>0)"],
    date_str: Annotated[str | None, "Fecha del gasto (YYYY-MM-DD); omitir usa hoy"] = None,
    store_id: Annotated[str | None, "Cadena del supermercado; omitir usa la del hogar"] = None,
    notes: Annotated[str | None, "Notas opcionales"] = None,
) -> dict[str, Any]:
    """Registra un gasto real del hogar."""

    with Session(mcp_engine()) as session:
        ctx = contexto_mcp(session)
        exigir_escritura(ctx)

        if date_str:
            try:
                date_spent = date.fromisoformat(date_str.strip())
            except ValueError as exc:
                raise ToolError(f"Fecha inválida: {date_str!r}. Usa YYYY-MM-DD.") from exc
        else:
            date_spent = None

        return _accionable(
            lambda: registrar_gasto(
                session,
                ctx.hogar.id,
                amount_clp,
                date_spent,
                store_id,
                None,  # category_id
                notes,
            )
        )


@mcp.tool
def get_spending_summary_tool(
    start_date: Annotated[str, "Fecha inicio del período (YYYY-MM-DD)"],
    end_date: Annotated[str | None, "Fecha fin (YYYY-MM-DD); omitir usa hoy"] = None,
    group_by: Annotated[str, "Agrupar por 'category' o 'store'"] = "category",
) -> dict[str, Any]:
    """Resumen de gastos agrupados."""
    with Session(mcp_engine()) as session:
        ctx = contexto_mcp(session)
        exigir_lectura(ctx)

        try:
            start = date.fromisoformat(start_date.strip())
        except ValueError as exc:
            raise ToolError(f"start_date inválida: {start_date!r}. Usa YYYY-MM-DD.") from exc

        end = None
        if end_date:
            try:
                end = date.fromisoformat(end_date.strip())
            except ValueError as exc:
                raise ToolError(f"end_date inválida: {end_date!r}. Usa YYYY-MM-DD.") from exc

        return _accionable(
            lambda: get_spending_summary(session, ctx.hogar.id, start, end, group_by)
        )


@mcp.tool
def get_budget_variance_tool(
    start_date: Annotated[str, "Fecha inicio del período (YYYY-MM-DD)"],
) -> dict[str, Any]:
    """Compara gastos reales vs presupuesto planificado del período."""
    with Session(mcp_engine()) as session:
        ctx = contexto_mcp(session)
        exigir_lectura(ctx)

        try:
            start = date.fromisoformat(start_date.strip())
        except ValueError as exc:
            raise ToolError(f"start_date inválida: {start_date!r}. Usa YYYY-MM-DD.") from exc

        return _accionable(lambda: get_budget_variance(session, ctx.hogar.id, start))


# === Shopping List ===

@mcp.tool
def generate_shopping_list(
    name: Annotated[str, "Nombre de la lista"] = "Lista de compras",
    plan_id: Annotated[int | None, "ID del plan para generar desde sus recetas"] = None,
    store_ids: Annotated[list[str] | None, "Cadenas a incluir"] = None,
) -> dict[str, Any]:
    """Genera lista de compras desde un plan, descuenta despensa."""
    with Session(mcp_engine()) as session:
        ctx = contexto_mcp(session)
        exigir_escritura(ctx)
        return _accionable(
            lambda: generar_lista(session, ctx.hogar.id, plan_id, store_ids, name)
        )


@mcp.tool
def get_shopping_list(
    list_id: Annotated[int, "ID de la lista"],
    group_by: Annotated[str, "Agrupar por 'aisle' o 'store'"] = "aisle",
) -> dict[str, Any]:
    """Detalles de una lista de compras."""
    with Session(mcp_engine()) as session:
        ctx = contexto_mcp(session)
        exigir_lectura(ctx)
        return _accionable(lambda: obtener_lista(session, ctx.hogar.id, list_id, group_by))


@mcp.tool
def compare_basket_across_stores_tool(
    list_id: Annotated[int, "ID de la lista"],
    threshold_pct: Annotated[float, "Umbral de ahorro para sugerir división"] = 0.10,
) -> dict[str, Any]:
    """Compara costo de la lista por cadena usando PPUM.

    Devuelve total por cadena y sugiere 'dividir la compra' si el ahorro supera el umbral."""
    with Session(mcp_engine()) as session:
        ctx = contexto_mcp(session)
        exigir_lectura(ctx)
        return _accionable(
            lambda: comparar_basket_across_stores(
                session, ctx.hogar.id, list_id, threshold_pct
            )
        )