# SPDX-License-Identifier: GPL-3.0-or-later
"""Endpoints de autenticación local (Task 13, spec §3.1).

- `POST /api/v1/auth/register`: registro con consentimiento afirmativo.
- `POST /api/v1/auth/login`: email + contraseña → Bearer (solo se guarda su hash).
- `GET  /api/v1/auth/me`: usuario autenticado (o owner implícito con `AUTH_MODE=none`).
- `GET  /api/v1/auth/privacy`: aviso de privacidad vigente que debe aceptarse.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.deps import settings_de_app, usuario_actual
from app.db import get_session
from app.models import User
from app.services.auth import (
    CredencialesInvalidas,
    EmailDuplicado,
    RegistroInvalido,
    aviso_privacidad,
    datos_usuario,
    emitir_token,
    iniciar_sesion,
    registrar,
)
from app.settings import Settings

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
SesionDep = Annotated[Session, Depends(get_session)]


class RegistroIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)
    household_name: str | None = Field(default=None, max_length=120)
    # Ley 21.719: checkbox no premarcado; el servidor exige `true` explícito.
    privacy_consent: bool = False
    privacy_notice_version: str | None = Field(default=None, max_length=32)


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


def _errores(fn: Any) -> Any:
    try:
        return fn()
    except EmailDuplicado as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RegistroInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except CredencialesInvalidas as exc:
        raise HTTPException(
            status_code=401, detail=str(exc), headers={"WWW-Authenticate": "Bearer"}
        ) from exc


def _sesion(usuario: User, token: str, session: Session) -> dict[str, Any]:
    return {
        "token": token,
        "token_type": "bearer",
        "user": datos_usuario(session, usuario),
    }


@router.get("/privacy")
def privacy() -> dict[str, Any]:
    """Aviso de privacidad vigente (texto y versión que debe aceptarse)."""
    return aviso_privacidad()


@router.post("/register", status_code=201)
def register(datos: RegistroIn, session: SesionDep) -> dict[str, Any]:
    """Crea la cuenta y su hogar (owner). Devuelve un Bearer listo para usar."""
    def accion() -> dict[str, Any]:
        usuario = registrar(
            session,
            email=datos.email,
            password=datos.password,
            display_name=datos.display_name,
            privacy_consent=datos.privacy_consent,
            privacy_notice_version=datos.privacy_notice_version,
            household_name=datos.household_name,
        )
        return _sesion(usuario, emitir_token(session, usuario), session)
    return _errores(accion)


@router.post("/login")
def login(datos: LoginIn, session: SesionDep) -> dict[str, Any]:
    """Verifica la contraseña (Argon2id) y emite un Bearer nuevo."""
    def accion() -> dict[str, Any]:
        usuario, token = iniciar_sesion(session, datos.email, datos.password)
        return _sesion(usuario, token, session)
    return _errores(accion)


@router.get("/me")
def me(
    session: SesionDep,
    usuario: Annotated[User, Depends(usuario_actual)],
    settings: Annotated[Settings, Depends(settings_de_app)],
) -> dict[str, Any]:
    """Usuario de la request; en `AUTH_MODE=none` es el owner implícito."""
    return {"auth_mode": settings.auth_mode, "user": datos_usuario(session, usuario)}
