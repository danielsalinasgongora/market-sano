# SPDX-License-Identifier: GPL-3.0-or-later
"""Endpoints de tokens de API (Task 15).

El valor en claro se muestra una sola vez al crearlo; luego solo metadatos.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.deps import usuario_actual
from app.db import get_session
from app.models import User
from app.services.tokens import (
    TokenInvalido,
    TokenSinPermiso,
    crear_token,
    listar_tokens,
    revocar_token,
)

router = APIRouter(prefix="/api/v1/tokens", tags=["tokens"])
SesionDep = Annotated[Session, Depends(get_session)]
UsuarioDep = Annotated[User, Depends(usuario_actual)]


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] | None = None


def _errores(fn: Any) -> Any:
    try:
        return fn()
    except TokenSinPermiso as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except TokenInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("", status_code=201)
def crear(datos: TokenIn, session: SesionDep, usuario: UsuarioDep) -> dict[str, Any]:
    """Crea un token con los scopes pedidos (limitados por el rol)."""
    return _errores(
        lambda: crear_token(session, usuario, name=datos.name, scopes=datos.scopes)
    )


@router.get("")
def listar(session: SesionDep, usuario: UsuarioDep) -> list[dict[str, Any]]:
    """Tokens del usuario (sin el valor ni el hash)."""
    return listar_tokens(session, usuario)


@router.delete("/{token_id}", status_code=204)
def revocar(token_id: int, session: SesionDep, usuario: UsuarioDep) -> Response:
    """Revoca un token propio; deja de autenticar de inmediato."""
    _errores(lambda: revocar_token(session, usuario, token_id))
    return Response(status_code=204)
