# SPDX-License-Identifier: GPL-3.0-or-later
"""Tools MCP de recetas (Task 10): detalle, alta con dry_run y calificación.

Con `AUTH_MODE=none` el invocador actúa como owner implícito del hogar por
defecto; los permisos por rol/token llegan en T15.
"""

from typing import Annotated, Any

from fastmcp.exceptions import ToolError
from pydantic import ValidationError
from sqlmodel import Session

from app.mcp.db import mcp_engine
from app.mcp.server import mcp
from app.services.identidad import SinHogar, owner_implicito
from app.services.imports import ImportInvalido, importar_desde_url
from app.services.recipes import (
    NoEncontrada,
    RecetaIn,
    RecetaInvalida,
    calificar,
    costo_receta,
    crear_receta,
    escalar_receta,
    obtener_receta,
)


def _accionable(fn: Any) -> Any:
    try:
        return fn()
    except (NoEncontrada, RecetaInvalida, SinHogar) as exc:
        raise ToolError(str(exc)) from exc
    except ImportInvalido as exc:
        raise ToolError(str(exc)) from exc
    except ValidationError as exc:
        raise ToolError(f"Receta inválida: {exc.errors(include_url=False)}") from exc


@mcp.tool
def get_recipe(recipe_id: Annotated[int, "ID de la receta"]) -> dict[str, Any]:
    """Detalle completo de una receta: ingredientes (en g/ml/unidad del catálogo),
    pasos con duración, etiquetas y calificación promedio."""
    with Session(mcp_engine()) as session:
        return _accionable(lambda: obtener_receta(session, recipe_id))


@mcp.tool
def create_recipe(
    title: Annotated[str, "Nombre de la receta"],
    ingredients: Annotated[
        list[dict[str, Any]],
        'Lista de {product (nombre o product_id del catálogo), quantity, unit (g|ml|unidad; '
        'también kg, L, cc), optional?, notes?}. Ej: {"product": "papa", "quantity": 1, '
        '"unit": "kg"}',
    ],
    steps: Annotated[
        list[dict[str, Any]] | None, "Pasos ordenados: {instruction, duration_minutes?}"
    ] = None,
    base_servings: Annotated[int, "Porciones base"] = 4,
    description: Annotated[str | None, "Descripción corta"] = None,
    instructions: Annotated[str | None, "Preparación en texto Markdown (opcional)"] = None,
    prep_minutes: Annotated[int | None, "Minutos de preparación"] = None,
    cook_minutes: Annotated[int | None, "Minutos de cocción"] = None,
    difficulty: Annotated[str | None, "facil | media | dificil"] = None,
    tags: Annotated[list[str] | None, 'Etiquetas, ej. ["chilena", "vegetariana"]'] = None,
    dry_run: Annotated[bool, "true (defecto): solo vista previa; false: guarda"] = True,
) -> dict[str, Any]:
    """Crea una receta propia del hogar con ingredientes del catálogo. Con
    dry_run=true valida y devuelve la vista previa sin guardar: muéstrala al
    usuario y repite con dry_run=false solo si la confirma. Si un ingrediente
    no está en el catálogo, el error sugiere nombres parecidos."""
    with Session(mcp_engine()) as session:
        def accion() -> dict[str, Any]:
            datos = RecetaIn(
                title=title, ingredients=ingredients, steps=steps or [],
                base_servings=base_servings, description=description,
                instructions=instructions, prep_minutes=prep_minutes,
                cook_minutes=cook_minutes, difficulty=difficulty, tags=tags or [],
            )
            hogar, usuario = owner_implicito(session)
            return crear_receta(session, hogar.id, datos, dry_run=dry_run, created_by=usuario.id)
        return _accionable(accion)


@mcp.tool
def scale_recipe(
    recipe_id: Annotated[int, "ID de la receta"],
    target_servings: Annotated[int, "Porciones objetivo (1 o más)"],
) -> dict[str, Any]:
    """Escala los ingredientes de una receta a `target_servings`.

    Reglas del Anexo A: unidades discretas (huevo, pan…) se redondean hacia
    arriba al entero; peso/volumen (g, ml) se mantiene con un decimal.
    Devuelve cada ingrediente con su cantidad original para comparar.
    """
    with Session(mcp_engine()) as session:
        return _accionable(lambda: escalar_receta(session, recipe_id, target_servings))


@mcp.tool
def get_recipe_cost(
    recipe_id: Annotated[int, "ID de la receta"],
    store_id: Annotated[
        str | None, "Cadena: jumbo, santaisabel o unimarc; omitir usa la del hogar"
    ] = None,
) -> dict[str, Any]:
    """Costo de una receta con el último precio de cada ingrediente.

    Devuelve total, costo por porción y desglose por ingrediente con el PPUM
    y la trazabilidad del precio (fuente, confianza, fecha, antigüedad).
    Si falta el precio de algún ingrediente, `is_complete=false` y `warning`
    explican qué falta; el total cubre solo lo valorizado.
    """
    with Session(mcp_engine()) as session:
        return _accionable(lambda: costo_receta(session, recipe_id, store_id))


@mcp.tool
def import_recipe(
    url: Annotated[str, "URL de la receta (http/https) con JSON-LD schema.org/Recipe"],
    dry_run: Annotated[bool, "true (defecto): solo vista previa; false: crea la receta"] = True,
) -> dict[str, Any]:
    """Importa una receta desde URL: descarga la página, extrae el JSON-LD y
    mapea los ingredientes al catálogo por nombre/alias.

    Con dry_run=true devuelve la vista previa sin guardar: muéstrala al usuario.
    Los ingredientes que no se pueden estructurar **no se pierden**: vuelven en
    `unresolved` con el motivo y sugerencias del catálogo; la receta se crea con
    los resueltos. Cada importación real deja un job con estado `completed` o
    `failed` (misma URL inválida incluida).
    """
    with Session(mcp_engine()) as session:
        def accion() -> dict[str, Any]:
            hogar, usuario = owner_implicito(session)
            return importar_desde_url(
                session, hogar.id, url, dry_run=dry_run, created_by=usuario.id
            )
        return _accionable(accion)


@mcp.tool
def rate_recipe(
    recipe_id: Annotated[int, "ID de la receta"],
    rating: Annotated[int, "Calificación de 1 a 5"],
) -> dict[str, Any]:
    """Califica una receta (1-5) para aprender los gustos del hogar. Devuelve el
    promedio actualizado."""
    with Session(mcp_engine()) as session:
        return _accionable(
            lambda: calificar(session, recipe_id, owner_implicito(session)[1].id, rating)
        )
