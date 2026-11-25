# SPDX-License-Identifier: GPL-3.0-or-later
"""MCP Resources para Market Sano (Task 23, spec §9.3).

Resources:
- household://{id}/context - Contexto del hogar
- meal-plan://{id} - Plan de comidas específico
- shopping-list://{id} - Lista de compras específica
- pantry://{id}/status - Estado de la despensa
"""

from fastmcp.exceptions import ToolError
from sqlmodel import Session

from app.mcp.db import mcp_engine
from app.mcp.permissions import contexto_mcp, exigir_lectura
from app.mcp.server import mcp
from app.models import Household, HouseholdPreference, PantryItem
from app.services.pantry import obtener_status


@mcp.resource("household://{household_id}/context")
def get_household_context_resource(household_id: int) -> dict:
    """Contexto del hogar: configuración, preferencias y miembros."""
    with Session(mcp_engine()) as session:
        ctx = contexto_mcp(session)
        exigir_lectura(ctx)

        hogar = session.get(Household, household_id)
        if hogar is None:
            raise ToolError(f"No existe el hogar {household_id}.")

        preferencia = session.get(HouseholdPreference, household_id)

        return {
            "id": hogar.id,
            "name": hogar.name,
            "currency": hogar.currency,
            "weekly_budget_clp": hogar.default_weekly_budget_clp,
            "default_store": preferencia.default_store_id if preferencia else None,
            "dietary_restrictions": preferencia.dietary_restrictions if preferencia else [],
            "allergies": preferencia.allergies if preferencia else [],
            "never_buy": preferencia.never_buy if preferencia else [],
            "comuna": preferencia.comuna if preferencia else None,
        }


@mcp.resource("meal-plan://{plan_id}")
def get_meal_plan_resource(plan_id: int) -> dict:
    """Detalles de un plan de comidas específico."""
    from app.services.planner import obtener_plan

    with Session(mcp_engine()) as session:
        ctx = contexto_mcp(session)
        exigir_lectura(ctx)

        try:
            return obtener_plan(session, ctx.hogar.id, plan_id)
        except Exception as e:
            return {"error": str(e)}


@mcp.resource("shopping-list://{list_id}")
def get_shopping_list_resource(list_id: int) -> dict:
    """Detalles de una lista de compras específica."""
    from app.services.shopping import obtener_lista

    with Session(mcp_engine()) as session:
        ctx = contexto_mcp(session)
        exigir_lectura(ctx)

        try:
            return obtener_lista(session, ctx.hogar.id, list_id)
        except Exception as e:
            return {"error": str(e)}


@mcp.resource("pantry://{household_id}/status")
def get_pantry_status_resource(household_id: int, expiring_within_days: int = 3) -> dict:
    """Estado de la despensa del hogar."""
    with Session(mcp_engine()) as session:
        ctx = contexto_mcp(session)
        exigir_lectura(ctx)

        return obtener_status(session, ctx.hogar.id, expiring_within_days)