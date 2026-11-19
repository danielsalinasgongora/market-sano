# SPDX-License-Identifier: GPL-3.0-or-later
"""Dependencias compartidas de la API: settings por app y usuario actual."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlmodel import Session

from app.db import get_session
from app.models import User
from app.services.auth import NoAutenticado, autenticar
from app.services.identidad import owner_implicito
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
