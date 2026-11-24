# SPDX-License-Identifier: GPL-3.0-or-later
"""Dependencias compartidas de la API: settings por app y usuario actual."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlmodel import Session

from app.db import get_session
from app.models import User
from app.models.enums import Role
from app.services.auth import NoAutenticado, autenticar, token_vigente
from app.services.households import (
    ROLES_ESCRITURA,
    ContextoHogar,
    HogarNoEncontrado,
    contexto_usuario,
)
from app.services.identidad import hogar_por_defecto, owner_implicito
from app.settings import Settings


def settings_de_app(request: Request) -> Settings:
    """Settings inyectados en `create_app` (tests con BD aislada incluidos)."""
    return request.app.state.settings


def usuario_actual(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(settings_de_app)],
) -> User:
    """Usuario de la request según `AUTH_MODE`.

    - `none`: owner implícito del hogar por defecto (sin login).
    - `local`: exige `Authorization: Bearer <token>`; sin token → 401.
    """
    if settings.auth_mode == "none":
        return owner_implicito(session)[1]
    try:
        return autenticar(session, request.headers.get("Authorization"))
    except NoAutenticado as exc:
        raise HTTPException(
            status_code=401,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def contexto(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(settings_de_app)],
    usuario: Annotated[User, Depends(usuario_actual)],
) -> ContextoHogar:
    """Hogar activo y rol del usuario.

    En `AUTH_MODE=none` es el hogar por defecto con rol owner. En `local`
    respeta `X-Household-Id` (si se envía) o usa el primer hogar del usuario.
    """
    if settings.auth_mode == "none":
        return ContextoHogar(hogar_por_defecto(session), usuario, Role.owner)
    cabecera = request.headers.get("X-Household-Id")
    household_id = None
    if cabecera:
        try:
            household_id = int(cabecera)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail="X-Household-Id debe ser un número entero."
            ) from exc
    try:
        return contexto_usuario(session, usuario, household_id)
    except HogarNoEncontrado as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def requiere_escritura(
    ctx: Annotated[ContextoHogar, Depends(contexto)],
) -> ContextoHogar:
    """403 si el rol es `viewer`; owner y member pueden escribir."""
    if ctx.rol not in ROLES_ESCRITURA:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Tu rol '{ctx.rol.value}' es de solo lectura; esta operación requiere "
                "owner o member."
            ),
        )
    return ctx


def _scopes_de_request(
    request: Request,
    session: Session,
    settings: Settings,
) -> frozenset[str]:
    """Scopes del Bearer actual; en `AUTH_MODE=none` el owner implícito tiene todos."""
    if settings.auth_mode == "none":
        return frozenset({"read", "write_draft", "confirm", "admin"})
    partes = (request.headers.get("Authorization") or "").split(None, 1)
    if len(partes) != 2 or partes[0].lower() != "bearer":
        return frozenset()
    fila = token_vigente(session, partes[1].strip())
    return frozenset(fila.scopes) if fila else frozenset()


def requiere_scope(scope: str) -> Callable[..., None]:
    """Dependencia que exige un scope del token (además del rol del hogar).

    Se usa en acciones sensibles como confirmar un plan: el login normal trae
    `read`+`write_draft`, así que confirmar exige un token con `confirm`.
    """

    def dependency(
        request: Request,
        session: Annotated[Session, Depends(get_session)],
        settings: Annotated[Settings, Depends(settings_de_app)],
    ) -> None:
        scopes = _scopes_de_request(request, session, settings)
        if scope in scopes or "admin" in scopes:
            return
        raise HTTPException(
            status_code=403,
            detail=(
                f"Esta acción requiere el scope '{scope}'. Crea un token con "
                f"`POST /api/v1/tokens` (scopes: {scope}) o usa `python -m "
                "app.create_token`."
            ),
        )

    return dependency
