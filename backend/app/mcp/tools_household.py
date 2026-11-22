# SPDX-License-Identifier: GPL-3.0-or-later
"""Tools MCP de hogar (Task 14): preferencias compartidas.

Con `AUTH_MODE=none` el invocador actúa como owner implícito del hogar por
defecto; los permisos por token/rol de MCP llegan en T15.
"""

from typing import Annotated, Any

from fastmcp.exceptions import ToolError
from sqlmodel import Session

from app.mcp.db import mcp_engine
from app.mcp.server import mcp
from app.services.households import (
    HogarNoEncontrado,
    SinPermiso,
    SolicitudInvalida,
    actualizar_preferencias,
    preferencias,
)
from app.services.identidad import SinHogar, owner_implicito


def _accionable(fn: Any) -> Any:
    try:
        return fn()
    except (HogarNoEncontrado, SinPermiso, SolicitudInvalida, SinHogar) as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool
def get_household_preferences() -> dict[str, Any]:
    """Preferencias del hogar: cadena por defecto, comuna, restricciones
    alimentarias, alergias y productos que nunca se compran."""
    with Session(mcp_engine()) as session:
        def accion() -> dict[str, Any]:
            hogar, usuario = owner_implicito(session)
            return preferencias(session, usuario, hogar.id)
        return _accionable(accion)


@mcp.tool
def update_household_preferences(
    default_store_id: Annotated[
        str | None, "Cadena por defecto: jumbo, santaisabel o unimarc"
    ] = None,
    dietary_restrictions: Annotated[
        list[str] | None, 'Restricciones, ej. ["vegetariana", "sin gluten"]'
    ] = None,
    allergies: Annotated[list[str] | None, 'Alergias, ej. ["maní", "mariscos"]'] = None,
    never_buy: Annotated[
        list[str] | None, 'Productos que nunca se compran, ej. ["bebida"]'
    ] = None,
    comuna: Annotated[str | None, "Comuna para disponibilidad de precios"] = None,
) -> dict[str, Any]:
    """Actualiza las preferencias compartidas del hogar (owner/member).

    Solo se cambian los campos enviados; para vaciar una lista envía `[]`.
    Devuelve las preferencias completas resultantes.
    """
    cambios = {
        campo: valor
        for campo, valor in {
            "default_store_id": default_store_id,
            "dietary_restrictions": dietary_restrictions,
            "allergies": allergies,
            "never_buy": never_buy,
            "comuna": comuna,
        }.items()
        if valor is not None
    }
    if not cambios:
        raise ToolError("Envía al menos una preferencia para actualizar.")

    with Session(mcp_engine()) as session:
        def accion() -> dict[str, Any]:
            hogar, usuario = owner_implicito(session)
            return actualizar_preferencias(session, usuario, hogar.id, cambios)
        return _accionable(accion)
