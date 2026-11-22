# SPDX-License-Identifier: GPL-3.0-or-later
"""Recetas (spec §3.2, Task 10): alta/edición con ingredientes estructurados,
búsqueda y calificaciones. Compartido por la API y las tools MCP.

Regla de oro: todo ingrediente resuelve a un `product_id` del catálogo en su
unidad canónica (g, ml, unidad). Se aceptan kg/L/cc y se convierten.
"""

import difflib
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlmodel import Session, delete, func, select

from app.models import (
    HouseholdPreference,
    ProductCatalog,
    Recipe,
    RecipeCollectionItem,
    RecipeIngredient,
    RecipeRating,
    RecipeStep,
    RecipeTag,
    StoreConnector,
)
from app.models.enums import Difficulty
from app.services.catalogo_abierto import FACTOR_UNIDAD
from app.services.prices import PrecioResuelto, get_latest_prices
from app.services.units import UNIDAD_PPUM, a_clp, costo_en_clp, escalar_cantidad


class RecetaInvalida(ValueError):
    """Datos de receta inválidos (mensaje accionable para el usuario o agente)."""


class NoEncontrada(LookupError):
    """La receta no existe o no pertenece al hogar."""


class IngredienteIn(BaseModel):
    product: str | int = Field(description="product_id o nombre/alias del catálogo")
    quantity: float = Field(gt=0)
    unit: str = Field(description="g, ml o unidad (se aceptan kg, L, cc)")
    optional: bool = False
    notes: str | None = Field(default=None, max_length=500)


class PasoIn(BaseModel):
    instruction: str = Field(min_length=1)
    duration_minutes: int | None = Field(default=None, ge=0)


class RecetaIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    base_servings: int = Field(default=4, ge=1)
    prep_minutes: int | None = Field(default=None, ge=0)
    cook_minutes: int | None = Field(default=None, ge=0)
    difficulty: Difficulty | None = None
    instructions: str | None = Field(default=None, description="Markdown")
    source_url: str | None = Field(default=None, max_length=2000)
    ingredients: list[IngredienteIn] = Field(min_length=1)
    steps: list[PasoIn] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


def _resolver_producto(
    ref: str | int, catalogo: list[ProductCatalog]
) -> ProductCatalog:
    if isinstance(ref, int) or str(ref).isdigit():
        producto = next((p for p in catalogo if p.id == int(ref)), None)
        if producto is None:
            raise RecetaInvalida(f"No existe el producto {ref}.")
        return producto
    nombre = str(ref).strip().lower()
    for p in catalogo:
        if nombre == p.canonical_name.lower() or nombre in (a.lower() for a in p.aliases):
            return p
    nombres = [p.canonical_name for p in catalogo]
    sugerencias = difflib.get_close_matches(nombre, nombres, n=3, cutoff=0.6)
    pista = f" ¿Quisiste decir: {', '.join(sugerencias)}?" if sugerencias else ""
    raise RecetaInvalida(
        f"'{ref}' no está en el catálogo.{pista} Puedes agregarlo con add_product_from_store."
    )


def _resolver_ingredientes(
    session: Session, ingredientes: list[IngredienteIn]
) -> list[tuple[ProductCatalog, IngredienteIn, float]]:
    """(producto, ingrediente, cantidad en unidad canónica) por cada ingrediente."""
    catalogo = list(session.exec(select(ProductCatalog)).all())
    resueltos = []
    for ing in ingredientes:
        producto = _resolver_producto(ing.product, catalogo)
        unidad = ing.unit.strip().lower()
        canonica, factor = FACTOR_UNIDAD.get(unidad, (unidad, 1))
        if canonica != producto.default_unit:
            raise RecetaInvalida(
                f"'{producto.canonical_name}' se mide en {producto.default_unit}; "
                f"llegó '{ing.unit}'."
            )
        resueltos.append((producto, ing, ing.quantity * factor))
    return resueltos


def _vista(datos: RecetaIn, resueltos: list, recipe_id: int | None) -> dict[str, Any]:
    return {
        "recipe_id": recipe_id,
        "title": datos.title,
        "base_servings": datos.base_servings,
        "time_minutes": (datos.prep_minutes or 0) + (datos.cook_minutes or 0),
        "difficulty": datos.difficulty.value if datos.difficulty else None,
        "source_url": datos.source_url,
        "ingredients": [
            {"product_id": p.id, "product_name": p.canonical_name, "quantity": cantidad,
             "unit": p.default_unit, "optional": ing.optional, "notes": ing.notes}
            for p, ing, cantidad in resueltos
        ],
        "steps": [s.model_dump() for s in datos.steps],
        "tags": sorted({t.strip().lower() for t in datos.tags if t.strip()}),
    }


def _escribir_hijos(session: Session, receta: Recipe, datos: RecetaIn, resueltos: list) -> None:
    for modelo in (RecipeIngredient, RecipeStep, RecipeTag):
        session.exec(delete(modelo).where(modelo.recipe_id == receta.id))
    for orden, (producto, ing, cantidad) in enumerate(resueltos):
        session.add(RecipeIngredient(
            recipe_id=receta.id, product_id=producto.id, quantity=cantidad,
            unit=producto.default_unit, optional=ing.optional, notes=ing.notes, sort_order=orden,
        ))
    for numero, paso in enumerate(datos.steps, start=1):
        session.add(RecipeStep(recipe_id=receta.id, step_number=numero,
                               instruction=paso.instruction,
                               duration_minutes=paso.duration_minutes))
    for etiqueta in sorted({t.strip().lower() for t in datos.tags if t.strip()}):
        session.add(RecipeTag(recipe_id=receta.id, tag=etiqueta))


def _aplicar(receta: Recipe, datos: RecetaIn) -> None:
    for campo in ("title", "description", "base_servings", "prep_minutes", "cook_minutes",
                  "difficulty", "instructions", "source_url"):
        setattr(receta, campo, getattr(datos, campo))
    receta.updated_at = datetime.now(UTC)


def crear_receta(
    session: Session, household_id: int, datos: RecetaIn, *, dry_run: bool,
    created_by: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Valida y crea la receta del hogar. dry_run → vista previa sin escribir."""
    resueltos = _resolver_ingredientes(session, datos.ingredients)
    if dry_run:
        return {"dry_run": True, **_vista(datos, resueltos, None)}
    receta = Recipe(household_id=household_id, created_by=created_by, title=datos.title)
    _aplicar(receta, datos)
    session.add(receta)
    session.flush()
    _escribir_hijos(session, receta, datos, resueltos)
    session.commit()
    return {"dry_run": False, **_vista(datos, resueltos, receta.id)}


def _receta_del_hogar(session: Session, recipe_id: int, household_id: int) -> Recipe:
    receta = session.get(Recipe, recipe_id)
    if receta is None:
        raise NoEncontrada(f"No existe la receta {recipe_id}.")
    if receta.household_id != household_id:
        raise RecetaInvalida(
            "Las recetas de la semilla/comunidad son de solo lectura; crea una copia propia."
        )
    return receta


def actualizar_receta(
    session: Session, household_id: int, recipe_id: int, datos: RecetaIn
) -> dict[str, Any]:
    receta = _receta_del_hogar(session, recipe_id, household_id)
    resueltos = _resolver_ingredientes(session, datos.ingredients)
    _aplicar(receta, datos)
    _escribir_hijos(session, receta, datos, resueltos)
    session.commit()
    return obtener_receta(session, recipe_id)


def eliminar_receta(session: Session, household_id: int, recipe_id: int) -> None:
    receta = _receta_del_hogar(session, recipe_id, household_id)
    for modelo in (RecipeIngredient, RecipeStep, RecipeTag, RecipeRating, RecipeCollectionItem):
        session.exec(delete(modelo).where(modelo.recipe_id == receta.id))
    session.delete(receta)
    session.commit()


def _rating(session: Session, recipe_id: int) -> tuple[float | None, int]:
    promedio, cantidad = session.exec(
        select(func.avg(RecipeRating.rating), func.count()).where(
            RecipeRating.recipe_id == recipe_id
        )
    ).one()
    return (round(promedio, 2) if promedio is not None else None), cantidad


def obtener_receta(session: Session, recipe_id: int) -> dict[str, Any]:
    receta = session.get(Recipe, recipe_id)
    if receta is None:
        raise NoEncontrada(f"No existe la receta {recipe_id}.")
    productos = {p.id: p for p in session.exec(select(ProductCatalog)).all()}
    ingredientes = session.exec(
        select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe_id)
        .order_by(RecipeIngredient.sort_order)
    ).all()
    pasos = session.exec(
        select(RecipeStep).where(RecipeStep.recipe_id == recipe_id).order_by(RecipeStep.step_number)
    ).all()
    tags = session.exec(select(RecipeTag.tag).where(RecipeTag.recipe_id == recipe_id)).all()
    promedio, cantidad = _rating(session, recipe_id)
    return {
        "recipe_id": receta.id,
        "household_id": receta.household_id,
        "title": receta.title,
        "description": receta.description,
        "base_servings": receta.base_servings,
        "prep_minutes": receta.prep_minutes,
        "cook_minutes": receta.cook_minutes,
        "difficulty": receta.difficulty.value if receta.difficulty else None,
        "instructions": receta.instructions,
        "source_url": receta.source_url,
        "ingredients": [
            {"product_id": i.product_id, "product_name": productos[i.product_id].canonical_name,
             "quantity": i.quantity, "unit": i.unit, "optional": i.optional, "notes": i.notes}
            for i in ingredientes
        ],
        "steps": [
            {"step_number": p.step_number, "instruction": p.instruction,
             "duration_minutes": p.duration_minutes}
            for p in pasos
        ],
        "tags": sorted(tags),
        "rating_avg": promedio,
        "rating_count": cantidad,
    }


def calificar(session: Session, recipe_id: int, user_id: uuid.UUID, rating: int) -> dict[str, Any]:
    """Guarda (o reemplaza) la calificación 1-5 del usuario; devuelve el promedio."""
    if not 1 <= rating <= 5:
        raise RecetaInvalida("rating debe estar entre 1 y 5.")
    if session.get(Recipe, recipe_id) is None:
        raise NoEncontrada(f"No existe la receta {recipe_id}.")
    fila = session.exec(
        select(RecipeRating).where(
            RecipeRating.recipe_id == recipe_id, RecipeRating.user_id == user_id
        )
    ).first() or RecipeRating(recipe_id=recipe_id, user_id=user_id, rating=rating)
    fila.rating, fila.rated_at = rating, datetime.now(UTC)
    session.add(fila)
    session.commit()
    promedio, cantidad = _rating(session, recipe_id)
    return {"recipe_id": recipe_id, "your_rating": rating, "rating_avg": promedio,
            "rating_count": cantidad}


def _store_preferido(session: Session, store_id: str | None) -> str:
    """Cadena para costos: la pedida, la del hogar o la primera registrada."""
    if store_id:
        return store_id
    preferencia = session.exec(
        select(HouseholdPreference).order_by(HouseholdPreference.household_id)
    ).first()
    if preferencia and preferencia.default_store_id:
        return preferencia.default_store_id
    conector = session.exec(select(StoreConnector).order_by(StoreConnector.name)).first()
    return conector.name if conector else "jumbo"


def _ingredientes_por_receta(session: Session) -> dict[int, list[RecipeIngredient]]:
    agrupados: dict[int, list[RecipeIngredient]] = {}
    for ingrediente in session.exec(
        select(RecipeIngredient).order_by(RecipeIngredient.sort_order)
    ).all():
        agrupados.setdefault(ingrediente.recipe_id, []).append(ingrediente)
    return agrupados


def _total_con_precios(
    ingredientes: list[RecipeIngredient], precios: dict[int, PrecioResuelto]
) -> tuple[int, bool]:
    """(total CLP, completo). `completo=False` si falta el precio de un ingrediente."""
    total, completo = 0, True
    for ingrediente in ingredientes:
        precio = precios.get(ingrediente.product_id)
        if precio is None:
            completo = False
            continue
        total += a_clp(
            costo_en_clp(ingrediente.quantity, ingrediente.unit,
                         precio.snapshot.unit_price_clp)
        )
    return total, completo


def escalar_receta(session: Session, recipe_id: int, target_servings: int) -> dict[str, Any]:
    """Escala las cantidades a `target_servings` con las reglas del Anexo A."""
    if target_servings < 1:
        raise RecetaInvalida("target_servings debe ser al menos 1.")
    receta = session.get(Recipe, recipe_id)
    if receta is None:
        raise NoEncontrada(f"No existe la receta {recipe_id}.")
    factor = target_servings / receta.base_servings
    productos = {p.id: p for p in session.exec(select(ProductCatalog)).all()}
    ingredientes = session.exec(
        select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe_id)
        .order_by(RecipeIngredient.sort_order)
    ).all()
    return {
        "recipe_id": receta.id,
        "title": receta.title,
        "base_servings": receta.base_servings,
        "target_servings": target_servings,
        "factor": round(factor, 4),
        "ingredients": [
            {
                "product_id": ing.product_id,
                "product_name": productos[ing.product_id].canonical_name,
                "quantity": escalar_cantidad(ing.quantity, ing.unit, factor),
                "original_quantity": ing.quantity,
                "unit": ing.unit,
                "optional": ing.optional,
                "notes": ing.notes,
            }
            for ing in ingredientes
        ],
    }


def costo_receta(
    session: Session, recipe_id: int, store_id: str | None = None
) -> dict[str, Any]:
    """Costo total y por porción con el último precio de cada ingrediente.

    Cada línea expone el PPUM usado y la trazabilidad completa del snapshot
    (`source`, `source_efectiva`, `confidence`, `fetched_at`, `is_stale`).
    Si a un ingrediente le falta precio, el total cubre solo lo que se pudo
    valorizar y la respuesta lo declara con `is_complete=false` + `warning`.
    """
    receta = session.get(Recipe, recipe_id)
    if receta is None:
        raise NoEncontrada(f"No existe la receta {recipe_id}.")
    cadena = _store_preferido(session, store_id)
    productos = {p.id: p for p in session.exec(select(ProductCatalog)).all()}
    ingredientes = session.exec(
        select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe_id)
        .order_by(RecipeIngredient.sort_order)
    ).all()
    precios = get_latest_prices(
        session, store_id=cadena, product_ids={i.product_id for i in ingredientes}
    )

    lineas: list[dict[str, Any]] = []
    faltantes: list[str] = []
    total = 0
    for ing in ingredientes:
        producto = productos[ing.product_id]
        precio = precios.get(ing.product_id)
        linea: dict[str, Any] = {
            "product_id": ing.product_id,
            "product_name": producto.canonical_name,
            "quantity": ing.quantity,
            "unit": ing.unit,
            "optional": ing.optional,
            "ppum_unit": UNIDAD_PPUM.get(ing.unit),
        }
        if precio is None:
            faltantes.append(producto.canonical_name)
            linea.update({"cost_clp": None, "unit_price_clp": None, "price": None})
        else:
            costo = a_clp(
                costo_en_clp(ing.quantity, ing.unit, precio.snapshot.unit_price_clp)
            )
            total += costo
            linea.update(
                {
                    "cost_clp": costo,
                    "unit_price_clp": precio.snapshot.unit_price_clp,
                    "price": precio.a_dict(),
                }
            )
        lineas.append(linea)

    respuesta: dict[str, Any] = {
        "recipe_id": receta.id,
        "title": receta.title,
        "store_id": cadena,
        "base_servings": receta.base_servings,
        "total_clp": total,
        "cost_per_serving_clp": a_clp(total / receta.base_servings),
        "is_complete": not faltantes,
        "missing_products": faltantes,
        "ingredients": lineas,
    }
    if faltantes:
        respuesta["warning"] = (
            f"Sin precio en {cadena} para: {', '.join(faltantes)}. El total cubre solo "
            "los ingredientes con precio; consulta el precio del producto para refrescarlo "
            "con el conector o registra uno manual."
        )
    return respuesta


def buscar_recetas(
    session: Session,
    query: str = "",
    tags: list[str] | None = None,
    max_cost_per_serving: float | None = None,
    max_time_minutes: int | None = None,
    store_id: str | None = None,
    sort: str = "title",
    max_results: int = 20,
    household_id: int | None = None,
) -> list[dict[str, Any]]:
    """Búsqueda combinable (spec §3.2): texto, tags AND, costo por porción y
    tiempo total; orden por título (defecto), costo o rating.

    El costo usa el último precio de cada ingrediente en `store_id` (defecto:
    la cadena del hogar) con su PPUM. Con `max_cost_per_serving` se excluyen
    las recetas con precios incompletos: un costo parcial no es comparable.
    (`only_with_pantry_match` se agrega en Task 19.)
    """
    if sort not in ("title", "cost", "rating"):
        raise RecetaInvalida("sort debe ser 'title', 'cost' o 'rating'.")
    if max_cost_per_serving is not None and max_cost_per_serving < 0:
        raise RecetaInvalida("max_cost_per_serving no puede ser negativo.")

    recetas = session.exec(select(Recipe)).all()
    etiquetas: dict[int, set[str]] = {}
    for fila in session.exec(select(RecipeTag)).all():
        etiquetas.setdefault(fila.recipe_id, set()).add(fila.tag)
    calificaciones: dict[int, tuple[float | None, int]] = {}
    for recipe_id, promedio, cantidad in session.exec(
        select(RecipeRating.recipe_id, func.avg(RecipeRating.rating), func.count())
        .group_by(RecipeRating.recipe_id)
    ).all():
        calificaciones[recipe_id] = (round(promedio, 2), cantidad)

    por_receta = _ingredientes_por_receta(session)
    precios = get_latest_prices(
        session,
        store_id=_store_preferido(session, store_id),
        product_ids={i.product_id for lista in por_receta.values() for i in lista},
    )

    texto = query.strip().lower()
    requeridas = {t.strip().lower() for t in tags or []}
    resultado = []
    for receta in recetas:
        if household_id is not None and receta.household_id not in (None, household_id):
            continue
        if texto and texto not in receta.title.lower() and texto not in (
            receta.description or ""
        ).lower():
            continue
        if not requeridas <= etiquetas.get(receta.id, set()):
            continue
        tiempo = (receta.prep_minutes or 0) + (receta.cook_minutes or 0)
        if max_time_minutes is not None and tiempo > max_time_minutes:
            continue
        total, completo = _total_con_precios(por_receta.get(receta.id, []), precios)
        costo_porcion = a_clp(total / receta.base_servings) if completo else None
        if max_cost_per_serving is not None and (
            costo_porcion is None or costo_porcion > max_cost_per_serving
        ):
            continue
        promedio, cantidad = calificaciones.get(receta.id, (None, 0))
        resultado.append({
            "recipe_id": receta.id,
            "title": receta.title,
            "base_servings": receta.base_servings,
            "time_minutes": tiempo,
            "difficulty": receta.difficulty.value if receta.difficulty else None,
            "tags": sorted(etiquetas.get(receta.id, set())),
            "own": receta.household_id is not None,
            "avg_rating": promedio,
            "rating_count": cantidad,
            "cost_per_serving_clp": costo_porcion,
            "is_complete_cost": completo,
        })

    if sort == "cost":
        resultado.sort(key=lambda r: (r["cost_per_serving_clp"] is None,
                                      r["cost_per_serving_clp"] or 0,
                                      r["title"].lower()))
    elif sort == "rating":
        resultado.sort(key=lambda r: (-(r["avg_rating"] or 0), -r["rating_count"],
                                      r["title"].lower()))
    else:
        resultado.sort(key=lambda r: r["title"].lower())
    return resultado[:max_results]
