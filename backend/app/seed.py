# SPDX-License-Identifier: GPL-3.0-or-later
"""Semilla de datos chilena de Market Sano.

Uso:
    python -m app.seed            # respeta DATABASE_URL de settings/.env
    docker compose exec -T app python -m app.seed

Es IDEMPOTENTE: puede ejecutarse todas las veces que se quiera sin duplicar
datos. Los catálogos se sincronizan por su clave única; las recetas recrean
sus ingredientes/pasos/tags en cada corrida (las calificaciones de los
usuarios NO se tocan) y la despensa demo solo se crea una vez.
"""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlmodel import Session, select

from app.db import get_engine
from app.models import (
    ExpenseCategory,
    Household,
    HouseholdPreference,
    PantryItem,
    PantryMovement,
    ProductCatalog,
    ProductStoreMatch,
    Recipe,
    RecipeIngredient,
    RecipeStep,
    RecipeTag,
    StoreConnector,
)
from app.models.enums import Difficulty, MovementReason, PantryLocation
from app.seed_data.matches import MATCHES_JUMBO, PESO_UNIDAD_G
from app.seed_data.products import PRODUCTOS
from app.seed_data.recipes import RECETAS
from app.settings import get_settings

BACKEND_DIR = Path(__file__).resolve().parent.parent

CATEGORIAS_GASTO = ["Supermercado", "Verdulería", "Carnicería", "Panadería", "Farmacia", "Otros"]

# Cadenas con fetch directo verificadas (ver docs/connectors): las otras dos
# requieren puente de navegador y quedan deshabilitadas por ahora.
CONECTORES = [
    {"name": "jumbo", "type": "mcp-supermercados-cl", "enabled": True,
     "config": {"fetch": "directo"}},
    {"name": "santaisabel", "type": "mcp-supermercados-cl", "enabled": True,
     "config": {"fetch": "directo"}},
    {"name": "unimarc", "type": "mcp-supermercados-cl", "enabled": True,
     "config": {"fetch": "directo"}},
    {"name": "lider", "type": "mcp-supermercados-cl", "enabled": False,
     "config": {"fetch": "puente-navegador"}},
    {"name": "tottus", "type": "mcp-supermercados-cl", "enabled": False,
     "config": {"fetch": "puente-navegador"}},
]

# (producto, cantidad, unidad, días de vencimiento o None)
DESPENSA_DEMO = [
    ("arroz", 500.0, "g", None),
    ("huevo", 6.0, "unidad", 21),
    ("aceite", 250.0, "ml", None),
    ("papa", 1000.0, "g", None),
    ("leche", 1000.0, "ml", 7),
]


def _hogar_defecto(session: Session) -> Household:
    """Hogar por defecto (AUTH_MODE=none). No sobrescribe datos existentes."""
    hogar = session.exec(select(Household).limit(1)).first()
    if hogar is None:
        hogar = Household(name="Mi Hogar", default_weekly_budget_clp=45000)
        session.add(hogar)
        session.flush()
    if session.get(HouseholdPreference, hogar.id) is None:
        session.add(HouseholdPreference(household_id=hogar.id, default_store_id="jumbo"))
    return hogar


def _seed_categorias(session: Session) -> int:
    for nombre in CATEGORIAS_GASTO:
        existente = session.exec(
            select(ExpenseCategory).where(ExpenseCategory.name == nombre)
        ).first()
        if existente is None:
            session.add(ExpenseCategory(name=nombre))
    return len(CATEGORIAS_GASTO)


def _seed_conectores(session: Session) -> int:
    for datos in CONECTORES:
        conector = session.exec(
            select(StoreConnector).where(StoreConnector.name == datos["name"])
        ).first()
        if conector is None:
            session.add(StoreConnector(**datos))
        else:
            conector.type = datos["type"]
            conector.enabled = datos["enabled"]
            conector.config = datos["config"]
    return len(CONECTORES)


def _seed_productos(session: Session) -> dict[str, ProductCatalog]:
    por_nombre: dict[str, ProductCatalog] = {}
    for nombre, categoria, unidad, compra, tamano, aliases in PRODUCTOS:
        producto = session.exec(
            select(ProductCatalog).where(ProductCatalog.canonical_name == nombre)
        ).first()
        if producto is None:
            producto = ProductCatalog(canonical_name=nombre)
            session.add(producto)
        producto.category = categoria
        producto.default_unit = unidad
        producto.purchase_unit = compra
        producto.purchase_size = tamano
        producto.aliases = list(aliases)
        por_nombre[nombre] = producto
    session.flush()
    return por_nombre


def _seed_matches(session: Session, por_nombre: dict[str, ProductCatalog]) -> int:
    """Matches curados y pesos por unidad: solo rellena lo que falta, nunca
    pisa un match o peso que el usuario haya cambiado (T9b)."""
    for nombre, peso in PESO_UNIDAD_G.items():
        if por_nombre[nombre].unit_weight_g is None:
            por_nombre[nombre].unit_weight_g = peso
    for nombre, url, sku in MATCHES_JUMBO:
        producto = por_nombre[nombre]
        existente = session.exec(
            select(ProductStoreMatch).where(
                ProductStoreMatch.product_id == producto.id,
                ProductStoreMatch.store_id == "jumbo",
            )
        ).first()
        if existente is None:
            session.add(
                ProductStoreMatch(product_id=producto.id, store_id="jumbo", store_url=url, sku=sku)
            )
    return len(MATCHES_JUMBO)


def _seed_recetas(session: Session, por_nombre: dict[str, ProductCatalog]) -> int:
    for datos in RECETAS:
        receta = session.exec(
            select(Recipe).where(Recipe.title == datos["titulo"], Recipe.household_id.is_(None))
        ).first()
        if receta is None:
            receta = Recipe(title=datos["titulo"], household_id=None)
            session.add(receta)
        receta.description = datos["descripcion"]
        receta.base_servings = datos["base_servings"]
        receta.prep_minutes = datos["prep_minutes"]
        receta.cook_minutes = datos["cook_minutes"]
        receta.difficulty = Difficulty(datos["dificultad"])
        receta.instructions = datos["instrucciones"]
        receta.updated_at = datetime.now(UTC)
        session.flush()

        # Hijos: recrear para mantener la semilla idempotente. Las
        # calificaciones (recipe_ratings) son datos del usuario y no se tocan.
        for ingrediente in session.exec(
            select(RecipeIngredient).where(RecipeIngredient.recipe_id == receta.id)
        ).all():
            session.delete(ingrediente)
        for paso in session.exec(
            select(RecipeStep).where(RecipeStep.recipe_id == receta.id)
        ).all():
            session.delete(paso)
        for etiqueta in session.exec(
            select(RecipeTag).where(RecipeTag.recipe_id == receta.id)
        ).all():
            session.delete(etiqueta)
        session.flush()

        for orden, (producto, cantidad, unidad, opcional, notas) in enumerate(
            datos["ingredientes"]
        ):
            session.add(
                RecipeIngredient(
                    recipe_id=receta.id,
                    product_id=por_nombre[producto].id,
                    quantity=cantidad,
                    unit=unidad,
                    optional=opcional,
                    notes=notas or None,
                    sort_order=orden,
                )
            )
        for numero, instruccion, duracion in datos["pasos"]:
            session.add(
                RecipeStep(
                    recipe_id=receta.id,
                    step_number=numero,
                    instruction=instruccion,
                    duration_minutes=duracion,
                )
            )
        for etiqueta in datos["tags"]:
            session.add(RecipeTag(recipe_id=receta.id, tag=etiqueta))
        session.flush()
    return len(RECETAS)


def _seed_despensa(
    session: Session, hogar: Household, por_nombre: dict[str, ProductCatalog]
) -> int:
    """Despensa demo: solo la primera vez; nunca toca datos del usuario."""
    existentes = session.exec(
        select(PantryItem).where(PantryItem.household_id == hogar.id)
    ).all()
    if existentes:
        return 0

    creados = 0
    for nombre, cantidad, unidad, dias in DESPENSA_DEMO:
        item = PantryItem(
            household_id=hogar.id,
            product_id=por_nombre[nombre].id,
            quantity=cantidad,
            unit=unidad,
            location=PantryLocation.alacena,
            expires_at=date.today() + timedelta(days=dias) if dias else None,
        )
        session.add(item)
        session.flush()
        session.add(
            PantryMovement(
                pantry_item_id=item.id,
                delta=cantidad,
                reason=MovementReason.purchase,
            )
        )
        creados += 1
    return creados


def _asegurar_esquema(database_url: str) -> None:
    """Aplica las migraciones pendientes (idempotente).

    El entrypoint del contenedor ya lo hace al arrancar, pero la semilla
    debe funcionar sola sobre cualquier BD, incluso recién creada.
    """
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


def seed(session: Session) -> dict[str, Any]:
    """Puebla la BD con datos chilenos de ejemplo. Idempotente."""
    hogar = _hogar_defecto(session)
    por_nombre = _seed_productos(session)
    recetas = _seed_recetas(session, por_nombre)
    categorias = _seed_categorias(session)
    conectores = _seed_conectores(session)
    matches = _seed_matches(session, por_nombre)
    despensa = _seed_despensa(session, hogar, por_nombre)
    session.commit()

    return {
        "hogar": hogar.name,
        "productos": len(PRODUCTOS),
        "recetas": recetas,
        "categorias_gasto": categorias,
        "conectores": conectores,
        "matches_cadena": matches,
        "despensa_demo": despensa,
    }


def main() -> None:
    settings = get_settings()
    # Crea el directorio de datos si falta (primer arranque local).
    get_engine(settings.database_url).dispose()
    # Asegura el esquema antes de sembrar.
    _asegurar_esquema(settings.database_url)

    engine = get_engine(settings.database_url)
    with Session(engine) as session:
        resumen = seed(session)
    engine.dispose()
    print("Market Sano: semilla aplicada")
    for clave, valor in resumen.items():
        print(f"  {clave}: {valor}")


if __name__ == "__main__":
    main()
