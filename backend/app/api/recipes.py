# SPDX-License-Identifier: GPL-3.0-or-later
"""Endpoints REST de recetas (spec §3.2, Task 10)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.db import get_session
from app.services.identidad import SinHogar, owner_implicito
from app.services.recipes import (
    NoEncontrada,
    RecetaIn,
    RecetaInvalida,
    actualizar_receta,
    buscar_recetas,
    calificar,
    crear_receta,
    eliminar_receta,
    obtener_receta,
)

router = APIRouter(tags=["recetas"])
SesionDep = Annotated[Session, Depends(get_session)]


class CalificacionIn(BaseModel):
    rating: int = Field(ge=1, le=5)


def _errores(fn: Any) -> Any:
    """Traduce errores de dominio a HTTP con el mensaje accionable."""
    try:
        return fn()
    except NoEncontrada as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RecetaInvalida, SinHogar) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/v1/recipes")
def listar_recetas(
    session: SesionDep,
    query: str = "",
    tags: Annotated[list[str] | None, Query()] = None,
    max_results: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[dict[str, Any]]:
    return buscar_recetas(session, query, tags, max_results)


@router.post("/api/v1/recipes", status_code=201)
def crear(datos: RecetaIn, session: SesionDep, dry_run: bool = False) -> dict[str, Any]:
    """Crea una receta propia del hogar. `dry_run=true` devuelve la vista previa."""
    def accion() -> dict[str, Any]:
        hogar, usuario = owner_implicito(session)
        return crear_receta(session, hogar.id, datos, dry_run=dry_run, created_by=usuario.id)
    return _errores(accion)


@router.get("/api/v1/recipes/{recipe_id}")
def detalle(recipe_id: int, session: SesionDep) -> dict[str, Any]:
    return _errores(lambda: obtener_receta(session, recipe_id))


@router.put("/api/v1/recipes/{recipe_id}")
def actualizar(recipe_id: int, datos: RecetaIn, session: SesionDep) -> dict[str, Any]:
    return _errores(
        lambda: actualizar_receta(session, owner_implicito(session)[0].id, recipe_id, datos)
    )


@router.delete("/api/v1/recipes/{recipe_id}", status_code=204)
def eliminar(recipe_id: int, session: SesionDep) -> Response:
    _errores(lambda: eliminar_receta(session, owner_implicito(session)[0].id, recipe_id))
    return Response(status_code=204)


@router.post("/api/v1/recipes/{recipe_id}/ratings")
def calificar_receta(recipe_id: int, datos: CalificacionIn, session: SesionDep) -> dict[str, Any]:
    return _errores(
        lambda: calificar(session, recipe_id, owner_implicito(session)[1].id, datos.rating)
    )
