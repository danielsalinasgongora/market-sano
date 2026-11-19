# SPDX-License-Identifier: GPL-3.0-or-later
"""Endpoints REST de recetas (spec §3.2, Task 10)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.db import get_session
from app.services.identidad import SinHogar, owner_implicito
from app.services.imports import ImportInvalido, importar_desde_url
from app.services.recipes import (
    NoEncontrada,
    RecetaIn,
    RecetaInvalida,
    actualizar_receta,
    buscar_recetas,
    calificar,
    costo_receta,
    crear_receta,
    eliminar_receta,
    escalar_receta,
    obtener_receta,
)

router = APIRouter(tags=["recetas"])
SesionDep = Annotated[Session, Depends(get_session)]


class CalificacionIn(BaseModel):
    rating: int = Field(ge=1, le=5)


class ImportacionIn(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


def _errores(fn: Any) -> Any:
    """Traduce errores de dominio a HTTP con el mensaje accionable."""
    try:
        return fn()
    except NoEncontrada as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RecetaInvalida, ImportInvalido, SinHogar) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/v1/recipes")
def listar_recetas(
    session: SesionDep,
    query: str = "",
    tags: Annotated[list[str] | None, Query()] = None,
    max_cost_per_serving: Annotated[float | None, Query(ge=0)] = None,
    max_time_minutes: Annotated[int | None, Query(ge=0)] = None,
    store_id: Annotated[
        str | None, Query(description="Cadena para costos; omitir usa la del hogar")
    ] = None,
    sort: Annotated[str, Query(description="title | cost | rating")] = "title",
    max_results: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[dict[str, Any]]:
    """Búsqueda con filtros combinables de costo por porción y tiempo total."""
    return _errores(
        lambda: buscar_recetas(
            session, query, tags, max_cost_per_serving, max_time_minutes,
            store_id, sort, max_results,
        )
    )


@router.post("/api/v1/recipes", status_code=201)
def crear(datos: RecetaIn, session: SesionDep, dry_run: bool = False) -> dict[str, Any]:
    """Crea una receta propia del hogar. `dry_run=true` devuelve la vista previa."""
    def accion() -> dict[str, Any]:
        hogar, usuario = owner_implicito(session)
        return crear_receta(session, hogar.id, datos, dry_run=dry_run, created_by=usuario.id)
    return _errores(accion)


@router.post("/api/v1/recipes/imports")
def importar(datos: ImportacionIn, session: SesionDep, dry_run: bool = True) -> dict[str, Any]:
    """Importa una receta desde una URL con JSON-LD (schema.org/Recipe).

    Con `dry_run=true` (defecto) devuelve la vista previa y no guarda nada; con
    `dry_run=false` crea la receta y deja el `recipe_import_job` con su estado.
    Los ingredientes que no se pueden mapear al catálogo vuelven en `unresolved`.
    """
    def accion() -> dict[str, Any]:
        hogar, usuario = owner_implicito(session)
        return importar_desde_url(
            session, hogar.id, datos.url, dry_run=dry_run, created_by=usuario.id
        )
    return _errores(accion)


@router.get("/api/v1/recipes/{recipe_id}")
def detalle(recipe_id: int, session: SesionDep) -> dict[str, Any]:
    return _errores(lambda: obtener_receta(session, recipe_id))


@router.get("/api/v1/recipes/{recipe_id}/scale")
def escalar(
    recipe_id: int,
    target_servings: Annotated[int, Query(ge=1)],
    session: SesionDep,
) -> dict[str, Any]:
    """Escala cantidades a `target_servings` (Anexo A: unidad → ceil, g/ml → 1 decimal)."""
    return _errores(lambda: escalar_receta(session, recipe_id, target_servings))


@router.get("/api/v1/recipes/{recipe_id}/cost")
def costo(
    recipe_id: int,
    session: SesionDep,
    store_id: Annotated[
        str | None, Query(description="Cadena; omitir usa la del hogar")
    ] = None,
) -> dict[str, Any]:
    """Costo total y por porción con desglose y trazabilidad de cada precio."""
    return _errores(lambda: costo_receta(session, recipe_id, store_id))


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
