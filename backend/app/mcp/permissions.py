# SPDX-License-Identifier: GPL-3.0-or-later
"""Permisos de las tools MCP por rol y scopes (Task 15, spec §3.7).

Identidad del proceso MCP: `MCP_API_TOKEN` (Bearer de `api_tokens`). Sin token,
`AUTH_MODE=none` opera como owner implícito del hogar por defecto. Los scopes
efectivos son la intersección entre los del token y el techo del rol:
`viewer`→read, `member`→read+write_draft, `owner`→todo (incluido confirm).
"""

import os
from dataclasses import dataclass

from fastmcp.exceptions import ToolError
from sqlmodel import Session, select

from app.models import Household, HouseholdMember, User
from app.models.enums import Role
from app.services.auth import NoAutenticado, autenticar, token_vigente
from app.services.identidad import owner_implicito

SCOPES = ("read", "write_draft", "confirm", "admin")
ROLE_SCOPES: dict[Role, frozenset[str]] = {
    Role.viewer: frozenset({"read"}),
    Role.member: frozenset({"read", "write_draft"}),
    Role.owner: frozenset(SCOPES),
}


@dataclass
class ContextoMCP:
    """Usuario, hogar activo, rol y scopes efectivos de una tool."""

    usuario: User
    hogar: Household
    rol: Role
    scopes: frozenset[str]

    def puede(self, scope: str) -> bool:
        return "admin" in self.scopes or scope in self.scopes


def scopes_del_rol(rol: Role) -> list[str]:
    """Scopes que un rol puede otorgar, en orden estable."""
    return [s for s in SCOPES if s in ROLE_SCOPES[rol]]


def _membresia(session: Session, user_id: object) -> tuple[Household, Role] | None:
    fila = session.exec(
        select(HouseholdMember)
        .where(HouseholdMember.user_id == user_id)
        .order_by(HouseholdMember.joined_at, HouseholdMember.id)
    ).first()
    if fila is None:
        return None
    hogar = session.get(Household, fila.household_id)
    return (hogar, fila.role) if hogar else None


def contexto_mcp(session: Session, authorization: str | None = None) -> ContextoMCP:
    """Resuelve la identidad del invocador y calcula sus scopes efectivos."""
    token = authorization or os.environ.get("MCP_API_TOKEN", "")
    if not token.strip():
        hogar, usuario = owner_implicito(session)
        return ContextoMCP(usuario, hogar, Role.owner, ROLE_SCOPES[Role.owner])

    try:
        usuario = autenticar(session, f"Bearer {token.strip()}")
    except NoAutenticado as exc:
        raise ToolError(
            "MCP_API_TOKEN inválido o revocado. Genera uno nuevo con "
            "`POST /api/v1/tokens` o `python -m app.create_token`."
        ) from exc

    membresia = _membresia(session, usuario.id)
    if membresia is None:
        raise ToolError(
            "Tu usuario no pertenece a ningún hogar. Crea uno o únete con un "
            "código de invitación antes de usar MCP."
        )
    hogar, rol = membresia
    fila = token_vigente(session, token.strip())
    scopes_token = set(fila.scopes) if fila else {"read"}
    efectivos = ROLE_SCOPES[rol] & scopes_token
    return ContextoMCP(usuario, hogar, rol, frozenset(efectivos))


def exigir(ctx: ContextoMCP, scope: str) -> None:
    """Lanza `ToolError` accionable si el scope efectivo no alcanza."""
    if not ctx.puede(scope):
        raise ToolError(
            f"Tu token/rol no permite '{scope}' (rol {ctx.rol.value}, scopes "
            f"{', '.join(sorted(ctx.scopes)) or 'ninguno'}). Pide un token con ese "
            "scope o usa una cuenta con más permisos."
        )


def exigir_lectura(ctx: ContextoMCP) -> None:
    exigir(ctx, "read")


def exigir_escritura(ctx: ContextoMCP) -> None:
    exigir(ctx, "write_draft")


def exigir_confirmacion(ctx: ContextoMCP) -> None:
    exigir(ctx, "confirm")
