# SPDX-License-Identifier: GPL-3.0-or-later
"""Tokens de API con scopes (Task 15, spec Anexo B).

El valor en claro se devuelve una sola vez; en `api_tokens` queda el SHA-256.
Los scopes pedidos no pueden exceder el techo del rol del usuario:
`viewer`→read, `member`→read+write_draft, `owner`→read+write_draft+confirm+admin.
"""

import secrets
from typing import Any

from sqlmodel import Session, select

from app.mcp.permissions import ROLE_SCOPES, SCOPES, scopes_del_rol
from app.models import ApiToken, HouseholdMember, User
from app.models.enums import Role
from app.services.auth import hash_token


class TokenInvalido(ValueError):
    """Nombre, scopes o token inexistente."""


class TokenSinPermiso(PermissionError):
    """El rol no puede otorgar esos scopes."""


def _rol_principal(session: Session, usuario: User) -> Role:
    filas = session.exec(
        select(HouseholdMember).where(HouseholdMember.user_id == usuario.id)
    ).all()
    if not filas:
        raise TokenInvalido(
            "Tu usuario no pertenece a ningún hogar; no hay rol con el cual emitir tokens."
        )
    orden = {Role.owner: 3, Role.member: 2, Role.viewer: 1}
    return max((fila.role for fila in filas), key=lambda r: orden[r])


def _normalizar_scopes(scopes: list[str] | None) -> list[str]:
    pedidos = {s.strip().lower() for s in scopes or ["read"] if s and s.strip()}
    if not pedidos:
        pedidos = {"read"}
    desconocidos = pedidos - set(SCOPES)
    if desconocidos:
        raise TokenInvalido(
            f"Scopes desconocidos: {', '.join(sorted(desconocidos))}. "
            f"Permitidos: {', '.join(SCOPES)}."
        )
    return [s for s in SCOPES if s in pedidos]


def crear_token(
    session: Session,
    usuario: User,
    *,
    name: str,
    scopes: list[str] | None = None,
) -> dict[str, Any]:
    """Emite un Bearer nuevo y devuelve el valor en claro una única vez."""
    nombre = (name or "").strip()
    if not nombre:
        raise TokenInvalido("Indica un nombre para identificar el token.")
    if len(nombre) > 120:
        raise TokenInvalido("El nombre del token no puede superar 120 caracteres.")

    rol = _rol_principal(session, usuario)
    pedidos = _normalizar_scopes(scopes)
    techo = ROLE_SCOPES[rol]
    excedidos = [s for s in pedidos if s not in techo]
    if excedidos:
        raise TokenSinPermiso(
            f"Tu rol '{rol.value}' no puede otorgar: {', '.join(excedidos)}. "
            f"Máximo para este rol: {', '.join(scopes_del_rol(rol))}."
        )

    token = secrets.token_urlsafe(32)
    fila = ApiToken(
        user_id=usuario.id,
        name=nombre,
        token_hash=hash_token(token),
        scopes=pedidos,
    )
    session.add(fila)
    session.commit()
    session.refresh(fila)
    return {
        "id": fila.id,
        "name": fila.name,
        "scopes": list(fila.scopes),
        "token": token,
        "token_type": "bearer",
        "created_at": fila.created_at.isoformat(),
        "warning": "Guarda este token ahora: no se volverá a mostrar.",
    }


def listar_tokens(session: Session, usuario: User) -> list[dict[str, Any]]:
    filas = session.exec(
        select(ApiToken)
        .where(ApiToken.user_id == usuario.id)
        .order_by(ApiToken.created_at, ApiToken.id)
    ).all()
    return [
        {
            "id": fila.id,
            "name": fila.name,
            "scopes": list(fila.scopes),
            "created_at": fila.created_at.isoformat(),
            "last_used_at": fila.last_used_at.isoformat() if fila.last_used_at else None,
        }
        for fila in filas
    ]


def revocar_token(session: Session, usuario: User, token_id: int) -> None:
    fila = session.get(ApiToken, token_id)
    if fila is None or fila.user_id != usuario.id:
        raise TokenInvalido(f"No existe el token {token_id} para tu usuario.")
    session.delete(fila)
    session.commit()
