# SPDX-License-Identifier: GPL-3.0-or-later
"""Endpoints REST de hogares, miembros, roles e invitaciones (Task 14)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.api.deps import usuario_actual
from app.db import get_session
from app.models import User
from app.models.enums import Role
from app.services.households import (
    HogarNoEncontrado,
    InvitacionInvalida,
    SinPermiso,
    SolicitudInvalida,
    actualizar_preferencias,
    crear_hogar,
    crear_invitacion,
    eliminar_hogar,
    exigir_rol,
    listar_hogares,
    miembros,
    preferencias,
    rol_en,
    unirse_con_codigo,
)

router = APIRouter(prefix="/api/v1/households", tags=["hogares"])
SesionDep = Annotated[Session, Depends(get_session)]
UsuarioDep = Annotated[User, Depends(usuario_actual)]


class HogarIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class InvitacionIn(BaseModel):
    ttl_hours: int = Field(default=24, ge=1, le=168)


class UnirseIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class PreferenciasIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_store_id: str | None = Field(default=None, max_length=64)
    dietary_restrictions: list[str] | None = None
    allergies: list[str] | None = None
    never_buy: list[str] | None = None
    comuna: str | None = Field(default=None, max_length=120)


def _errores(fn: Any) -> Any:
    try:
        return fn()
    except HogarNoEncontrado as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SinPermiso as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (InvitacionInvalida, SolicitudInvalida) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _detalle(session: Session, usuario: User, household_id: int) -> dict[str, Any]:
    hogar = exigir_rol(session, usuario, household_id, frozenset(Role))
    return {
        "household_id": hogar.id,
        "name": hogar.name,
        "currency": hogar.currency,
        "timezone": hogar.timezone,
        "default_weekly_budget_clp": hogar.default_weekly_budget_clp,
        "role": rol_en(session, usuario, household_id).value,
        "preferences": preferencias(session, usuario, household_id),
    }


@router.get("")
def listar(session: SesionDep, usuario: UsuarioDep) -> list[dict[str, Any]]:
    """Hogares del usuario con su rol y cantidad de miembros."""
    return listar_hogares(session, usuario)


@router.post("", status_code=201)
def crear(datos: HogarIn, session: SesionDep, usuario: UsuarioDep) -> dict[str, Any]:
    """Crea un hogar nuevo; el creador queda como owner."""
    return _errores(lambda: crear_hogar(session, usuario, datos.name))


@router.post("/join")
def unirse(datos: UnirseIn, session: SesionDep, usuario: UsuarioDep) -> dict[str, Any]:
    """Une al usuario a un hogar con un código de invitación de un solo uso."""
    return _errores(lambda: unirse_con_codigo(session, usuario, datos.code))


@router.get("/{household_id}")
def detalle(household_id: int, session: SesionDep, usuario: UsuarioDep) -> dict[str, Any]:
    return _errores(lambda: _detalle(session, usuario, household_id))


@router.get("/{household_id}/members")
def listar_miembros(
    household_id: int, session: SesionDep, usuario: UsuarioDep
) -> list[dict[str, Any]]:
    return _errores(lambda: miembros(session, usuario, household_id))


@router.post("/{household_id}/invitations", status_code=201)
def invitar(
    household_id: int,
    datos: InvitacionIn,
    session: SesionDep,
    usuario: UsuarioDep,
) -> dict[str, Any]:
    """Genera un código alfanumérico de un solo uso (24 h por defecto)."""
    return _errores(
        lambda: crear_invitacion(session, usuario, household_id, datos.ttl_hours)
    )


@router.get("/{household_id}/preferences")
def leer_preferencias(
    household_id: int, session: SesionDep, usuario: UsuarioDep
) -> dict[str, Any]:
    return _errores(lambda: preferencias(session, usuario, household_id))


@router.put("/{household_id}/preferences")
def actualizar_preferencias_hogar(
    household_id: int,
    datos: PreferenciasIn,
    session: SesionDep,
    usuario: UsuarioDep,
) -> dict[str, Any]:
    """Actualiza preferencias parciales; requiere owner o member."""
    return _errores(
        lambda: actualizar_preferencias(
            session, usuario, household_id, datos.model_dump(exclude_unset=True)
        )
    )


@router.delete("/{household_id}", status_code=204)
def borrar(household_id: int, session: SesionDep, usuario: UsuarioDep) -> Response:
    """Borra el hogar y todos sus datos dependientes (solo owner)."""
    _errores(lambda: eliminar_hogar(session, usuario, household_id))
    return Response(status_code=204)
