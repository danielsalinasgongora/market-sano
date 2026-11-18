# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests de la semilla chilena (Task 4): idempotencia e integridad."""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, select

from app.db import get_engine
from app.models import (
    ExpenseCategory,
    Household,
    HouseholdPreference,
    PantryItem,
    ProductCatalog,
    Recipe,
    RecipeIngredient,
    RecipeStep,
    RecipeTag,
    StoreConnector,
)
from app.seed import DESPENSA_DEMO, seed
from app.seed_data.equivalences import EQUIVALENCIAS_VOLUMEN_ML, PESO_POR_TAZA_G
from app.seed_data.products import PRODUCTOS
from app.seed_data.recipes import RECETAS


def test_catalogo_y_hogar_completos(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        resumen = seed(session)

    assert resumen["productos"] == len(PRODUCTOS)
    assert len(PRODUCTOS) >= 100
    assert resumen["recetas"] == len(RECETAS)
    assert 10 <= len(RECETAS) <= 15

    with Session(migrated_engine) as session:
        # Aliases regionales documentados en la spec (Anexo D).
        palta = session.exec(
            select(ProductCatalog).where(ProductCatalog.canonical_name == "palta")
        ).one()
        assert "aguacate" in palta.aliases
        porotos = session.exec(
            select(ProductCatalog).where(ProductCatalog.canonical_name == "porotos")
        ).one()
        assert "frijol" in porotos.aliases

        # Conectores: 3 cadenas de fetch directo habilitadas.
        habilitados = session.exec(
            select(StoreConnector).where(StoreConnector.enabled)  # type: ignore[arg-type]
        ).all()
        assert {c.name for c in habilitados} == {"jumbo", "santaisabel", "unimarc"}

        # Hogar por defecto con presupuesto semanal y preferencias.
        hogar = session.exec(select(Household)).one()
        assert hogar.default_weekly_budget_clp == 45000
        preferencias = session.get(HouseholdPreference, hogar.id)
        assert preferencias is not None
        assert preferencias.default_store_id == "jumbo"

        # Categorías de gasto por defecto.
        categorias = session.exec(select(ExpenseCategory)).all()
        assert {c.name for c in categorias} >= {
            "Supermercado", "Verdulería", "Carnicería", "Panadería", "Farmacia", "Otros",
        }


def test_recetas_resuelven_ingredientes_al_catalogo(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        seed(session)

    with Session(migrated_engine) as session:
        productos = {p.id: p for p in session.exec(select(ProductCatalog)).all()}
        recetas = session.exec(select(Recipe)).all()
        assert len(recetas) == len(RECETAS)

        for receta in recetas:
            ingredientes = session.exec(
                select(RecipeIngredient).where(RecipeIngredient.recipe_id == receta.id)
            ).all()
            pasos = session.exec(
                select(RecipeStep).where(RecipeStep.recipe_id == receta.id)
            ).all()
            etiquetas = session.exec(
                select(RecipeTag).where(RecipeTag.recipe_id == receta.id)
            ).all()
            assert ingredientes, receta.title
            assert pasos, receta.title
            assert etiquetas, receta.title
            assert receta.instructions

            for ingrediente in ingredientes:
                producto = productos[ingrediente.product_id]
                # La unidad de cada ingrediente es la canónica del producto (spec §3.2).
                assert ingrediente.unit == producto.default_unit, (
                    receta.title,
                    producto.canonical_name,
                )

        # Catálogo sano: unidad canónica siempre; compra con tamaño coherente.
        for producto in productos.values():
            assert producto.default_unit in {"g", "ml", "unidad"}, producto.canonical_name
            if producto.purchase_unit is not None:
                assert producto.purchase_size is not None
                assert producto.purchase_size > 0


def test_semilla_idempotente(migrated_engine: Engine) -> None:
    with Session(migrated_engine) as session:
        primera = seed(session)
    with Session(migrated_engine) as session:
        segunda = seed(session)

    # La despensa demo solo se crea la primera vez (por diseño).
    assert primera["despensa_demo"] == len(DESPENSA_DEMO)
    assert segunda["despensa_demo"] == 0
    primera.pop("despensa_demo")
    segunda.pop("despensa_demo")
    assert primera == segunda

    with Session(migrated_engine) as session:
        total_productos = session.exec(select(ProductCatalog)).all()
        assert len(total_productos) == len(PRODUCTOS)

        # Las cantidades de la despensa no se duplicaron.
        despensa = session.exec(select(PantryItem)).all()
        assert len(despensa) == len(DESPENSA_DEMO)
        cantidades = sorted(item.quantity for item in despensa)
        esperadas = sorted(cantidad for _, cantidad, _, _ in DESPENSA_DEMO)
        assert cantidades == esperadas

        # Ingredientes por receta estables (recreados, no duplicados).
        receta = session.exec(select(Recipe)).first()
        assert receta is not None
        ingredientes = session.exec(
            select(RecipeIngredient).where(RecipeIngredient.recipe_id == receta.id)
        ).all()
        datos = next(r for r in RECETAS if r["titulo"] == receta.title)
        assert len(ingredientes) == len(datos["ingredientes"])


def test_equivalencias_de_cocina_sanas() -> None:
    """Anexo A: la tabla de equivalencias debe ser coherente."""
    assert 0 < EQUIVALENCIAS_VOLUMEN_ML["pizca"] < EQUIVALENCIAS_VOLUMEN_ML["cucharadita"]
    assert EQUIVALENCIAS_VOLUMEN_ML["cucharadita"] < EQUIVALENCIAS_VOLUMEN_ML["cucharada"]
    assert EQUIVALENCIAS_VOLUMEN_ML["cucharada"] < EQUIVALENCIAS_VOLUMEN_ML["taza"]
    assert PESO_POR_TAZA_G["harina"] < PESO_POR_TAZA_G["arroz"]


def test_cli_python_m_seed(tmp_path: Path) -> None:
    """AC de la Task 4: `python -m app.seed` corre por CLI y es idempotente."""
    db_url = f"sqlite:///{tmp_path.as_posix()}/cli.sqlite3"
    env = {**os.environ, "DATABASE_URL": db_url}

    for _ in range(2):
        resultado = subprocess.run(
            [sys.executable, "-m", "app.seed"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert resultado.returncode == 0, resultado.stderr
        assert "Market Sano: semilla aplicada" in resultado.stdout

    engine = get_engine(db_url)
    with Session(engine) as session:
        assert len(session.exec(select(ProductCatalog)).all()) == len(PRODUCTOS)
        assert len(session.exec(select(Recipe)).all()) == len(RECETAS)
        assert len(session.exec(select(PantryItem)).all()) == len(DESPENSA_DEMO)
    engine.dispose()
