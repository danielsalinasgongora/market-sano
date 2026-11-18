# SPDX-License-Identifier: GPL-3.0-or-later
"""Tools MCP de lectura (Fase 0): hogar, recetas y despensa (spec §3.1-§3.3).

Permisos: solo lectura. Con `AUTH_MODE=none` no requieren autenticación;
el invocador opera como owner implícito del hogar por defecto. Las tools
de escritura (con `dry_run` y tokens de confirmación) llegan en la Fase 2
del plan (tasks/todo.md).
"""

from datetime import date, timedelta
from typing import Annotated, Any

from fastmcp.exceptions import ToolError
from sqlmodel import Session, select

from app.mcp.db import mcp_engine
from app.mcp.server import mcp
from app.models import (
    Household,
    HouseholdPreference,
    PantryItem,
    ProductCatalog,
)
from app.models.enums import PantryLocation
from app.services.recipes import buscar_recetas


def _hogar(session: Session, household_id: int | None) -> Household:
    """Resuelve el hogar por ID o el primero (modo single-user)."""
    if household_id is not None:
        hogar = session.get(Household, household_id)
        if hogar is None:
            raise ToolError(f"No existe el hogar {household_id}.")
        return hogar
    hogar = session.exec(select(Household).limit(1)).first()
    if hogar is None:
        raise ToolError(
            "La base no tiene hogares. Ejecuta `python -m app.seed` para crear "
            "el hogar por defecto con datos de ejemplo."
        )
    return hogar


def _contexto(session: Session, hogar: Household) -> dict[str, Any]:
    preferencias = session.get(HouseholdPreference, hogar.id)
    return {
        "id": hogar.id,
        "name": hogar.name,
        "currency": hogar.currency,
        "timezone": hogar.timezone,
        "weekly_budget_clp": hogar.default_weekly_budget_clp,
        "default_store": preferencias.default_store_id if preferencias else None,
        "dietary_restrictions": preferencias.dietary_restrictions if preferencias else [],
        "allergies": preferencias.allergies if preferencias else [],
        "never_buy": preferencias.never_buy if preferencias else [],
        "comuna": preferencias.comuna if preferencias else None,
    }


@mcp.tool
def get_household_context(
    household_id: Annotated[int | None, "ID del hogar; omitir usa el hogar por defecto"] = None,
) -> dict[str, Any]:
    """Devuelve la configuración del hogar: presupuesto semanal en CLP, tienda
    por defecto, restricciones dietéticas, alergias y comuna."""
    with Session(mcp_engine()) as session:
        return _contexto(session, _hogar(session, household_id))


@mcp.tool
def search_recipes(
    query: Annotated[str, "Texto a buscar en título o descripción (vacío: todas)"] = "",
    tags: Annotated[list[str] | None, "La receta debe tener TODAS estas etiquetas (AND)"] = None,
    max_results: Annotated[int, "Máximo de resultados a devolver"] = 20,
) -> list[dict[str, Any]]:
    """Busca recetas por texto y etiquetas.

    Versión Fase 0 (spec §3.2): los filtros `max_cost_per_serving`,
    `max_time_minutes` y `only_with_pantry_match` se agregan cuando exista la
    capa de costos por porción (Task 11 del plan).
    """
    with Session(mcp_engine()) as session:
        return buscar_recetas(session, query, tags, max_results)


@mcp.tool
def get_pantry_status(
    household_id: Annotated[int | None, "ID del hogar; omitir usa el hogar por defecto"] = None,
    location: Annotated[
        str | None, "Filtrar por ubicación: refrigerador | congelador | alacena | otro"
    ] = None,
    expiring_within_days: Annotated[
        int | None, "Solo ítems cuya fecha de vencimiento es en N días o menos"
    ] = None,
) -> list[dict[str, Any]]:
    """Devuelve el estado de la despensa: cantidades por producto, ubicación
    e ítems próximos a vencer."""
    with Session(mcp_engine()) as session:
        hogar = _hogar(session, household_id)
        statement = select(PantryItem).where(PantryItem.household_id == hogar.id)
        if location:
            try:
                ubicacion = PantryLocation(location)
            except ValueError as exc:
                raise ToolError(
                    "location debe ser una de: refrigerador, congelador, alacena, otro."
                ) from exc
            statement = statement.where(PantryItem.location == ubicacion)  # type: ignore[arg-type]

        items = session.exec(statement).all()
        productos = {p.id: p for p in session.exec(select(ProductCatalog)).all()}

        limite = None
        if expiring_within_days:
            limite = date.today() + timedelta(days=expiring_within_days)
        resultado: list[dict[str, Any]] = []
        for item in items:
            if limite is not None:
                if item.expires_at is None or item.expires_at > limite:
                    continue
            resultado.append(
                {
                    "product_id": item.product_id,
                    "product_name": productos[item.product_id].canonical_name,
                    "quantity": item.quantity,
                    "unit": item.unit,
                    "location": item.location.value,
                    "expires_at": item.expires_at.isoformat() if item.expires_at else None,
                }
            )
        return resultado


@mcp.resource("household://{id}/context")
def household_context(id: Annotated[str, "ID del hogar"]) -> dict[str, Any]:
    """Recurso MCP: configuración completa del hogar (spec §3.7)."""
    try:
        household_id = int(id)
    except ValueError as exc:
        raise ToolError(f"id de hogar inválido: {id}") from exc
    with Session(mcp_engine()) as session:
        return _contexto(session, _hogar(session, household_id))
