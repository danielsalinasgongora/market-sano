# SPDX-License-Identifier: GPL-3.0-or-later
"""Endpoints REST de recetas (spec §3.2, Task 10)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.deps import contexto, requiere_escritura
from app.db import get_session
from app.models import Recipe
from app.services.households import ContextoHogar
from app.services.identidad import SinHogar
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


def _exigir_visible(session: Session, ctx: ContextoHogar, recipe_id: int) -> None:
    """404 si la receta es privada de otro hogar (las públicas son visibles)."""
    receta = session.get(Recipe, recipe_id)
    if receta is not None and receta.household_id not in (None, ctx.hogar.id):
        raise HTTPException(
            status_code=404, detail=f"No existe la receta {recipe_id}."
        )


@router.get("/api/v1/recipes")
def listar_recetas(
    session: SesionDep,
    ctx: Annotated[ContextoHogar, Depends(contexto)],
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
    """Búsqueda con filtros combinables de costo por porción y tiempo total.

    Devuelve recetas del hogar activo y las públicas/comunitarias.
    """
    return _errores(
        lambda: buscar_recetas(
            session, query, tags, max_cost_per_serving, max_time_minutes,
            store_id, sort, max_results, household_id=ctx.hogar.id,
        )
    )


@router.post("/api/v1/recipes", status_code=201)
def crear(
    datos: RecetaIn,
    session: SesionDep,
    ctx: Annotated[ContextoHogar, Depends(requiere_escritura)],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Crea una receta propia del hogar. `dry_run=true` devuelve la vista previa."""
    def accion() -> dict[str, Any]:
        return crear_receta(
            session, ctx.hogar.id, datos, dry_run=dry_run, created_by=ctx.usuario.id
        )
    return _errores(accion)


@router.post("/api/v1/recipes/imports")
def importar(
    datos: ImportacionIn,
    session: SesionDep,
    ctx: Annotated[ContextoHogar, Depends(requiere_escritura)],
    dry_run: bool = True,
) -> dict[str, Any]:
    """Importa una receta desde una URL con JSON-LD (schema.org/Recipe).

    Con `dry_run=true` (defecto) devuelve la vista previa y no guarda nada; con
    `dry_run=false` crea la receta y deja el `recipe_import_job` con su estado.
    Los ingredientes que no se pueden mapear al catálogo vuelven en `unresolved`.
    """
    def accion() -> dict[str, Any]:
        return importar_desde_url(
            session, ctx.hogar.id, datos.url, dry_run=dry_run, created_by=ctx.usuario.id
        )
    return _errores(accion)


@router.get("/api/v1/recipes/{recipe_id}")
def detalle(
    recipe_id: int,
    session: SesionDep,
    ctx: Annotated[ContextoHogar, Depends(contexto)],
) -> dict[str, Any]:
    _exigir_visible(session, ctx, recipe_id)
    return _errores(lambda: obtener_receta(session, recipe_id))


@router.get("/api/v1/recipes/{recipe_id}/scale")
def escalar(
    recipe_id: int,
    target_servings: Annotated[int, Query(ge=1)],
    session: SesionDep,
    ctx: Annotated[ContextoHogar, Depends(contexto)],
) -> dict[str, Any]:
    """Escala cantidades a `target_servings` (Anexo A: unidad → ceil, g/ml → 1 decimal)."""
    _exigir_visible(session, ctx, recipe_id)
    return _errores(lambda: escalar_receta(session, recipe_id, target_servings))


@router.get("/api/v1/recipes/{recipe_id}/cost")
def costo(
    recipe_id: int,
    session: SesionDep,
    ctx: Annotated[ContextoHogar, Depends(contexto)],
    store_id: Annotated[
        str | None, Query(description="Cadena; omitir usa la del hogar")
    ] = None,
) -> dict[str, Any]:
    """Costo total y por porción con desglose y trazabilidad de cada precio."""
    _exigir_visible(session, ctx, recipe_id)
    return _errores(lambda: costo_receta(session, recipe_id, store_id))


@router.put("/api/v1/recipes/{recipe_id}")
def actualizar(
    recipe_id: int,
    datos: RecetaIn,
    session: SesionDep,
    ctx: Annotated[ContextoHogar, Depends(requiere_escritura)],
) -> dict[str, Any]:
    return _errores(
        lambda: actualizar_receta(session, ctx.hogar.id, recipe_id, datos)
    )


@router.delete("/api/v1/recipes/{recipe_id}", status_code=204)
def eliminar(
    recipe_id: int,
    session: SesionDep,
    ctx: Annotated[ContextoHogar, Depends(requiere_escritura)],
) -> Response:
    _errores(lambda: eliminar_receta(session, ctx.hogar.id, recipe_id))
    return Response(status_code=204)


@router.post("/api/v1/recipes/{recipe_id}/ratings")
def calificar_receta(
    recipe_id: int,
    datos: CalificacionIn,
    session: SesionDep,
    ctx: Annotated[ContextoHogar, Depends(requiere_escritura)],
) -> dict[str, Any]:
    _exigir_visible(session, ctx, recipe_id)
    return _errores(
        lambda: calificar(session, recipe_id, ctx.usuario.id, datos.rating)
    )
