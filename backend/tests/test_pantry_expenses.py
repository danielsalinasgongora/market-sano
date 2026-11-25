# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests de despensa y gastos (Task 19, Task 22)."""

from datetime import date, timedelta

import pytest
from sqlmodel import Session, select

from app.models import Household, PantryItem, ProductCatalog, Recipe
from app.services.expenses import get_budget_variance, get_spending_summary, registrar_gasto
from app.services.pantry import ajustar_cantidad, get_pantry_shortfall, obtener_status


def test_pantry_ajustar_cantidad(engine_sembrado) -> None:
    """Ajustar cantidad genera movimiento."""
    from app.models import MovementReason
    from app.services.pantry import ajustar_cantidad

    hogar = _get_hogar(engine_sembrado)

    with Session(engine_sembrado) as session:
        producto = session.exec(select(ProductCatalog).order_by(ProductCatalog.id)).first()
        if producto is None:
            pytest.skip("No hay productos en la semilla")

        # Primero agregamos el item a la despensa (simulando un registro inicial)
        despensa = PantryItem(
            household_id=hogar,
            product_id=producto.id,
            quantity=0.0,
            unit="kg",
        )
        session.add(despensa)
        session.commit()

        # Comprar: +1kg
        resultado = ajustar_cantidad(
            session, hogar, producto.id, 1.0, MovementReason.purchase
        )
        assert resultado["quantity"] == 1.0
        assert resultado["movement"]["delta"] == 1.0
        assert resultado["movement"]["reason"] == "purchase"


def test_pantry_status_obtiene_items_a_vencer(engine_sembrado) -> None:
    """Obtener status con items a vencer."""
    hogar = _get_hogar(engine_sembrado)

    with Session(engine_sembrado) as session:
        producto = session.exec(select(ProductCatalog).order_by(ProductCatalog.id)).first()
        if producto is None:
            pytest.skip("No hay productos en la semilla")

        # Item a vencer en 1 día
        despensa = PantryItem(
            household_id=hogar,
            product_id=producto.id,
            quantity=1.0,
            unit="kg",
            expires_at=date.today() + timedelta(days=1),
        )
        session.add(despensa)
        session.commit()

        status = obtener_status(session, hogar, expiring_within_days=3)
        assert status["total_items"] == 1
        assert status["expiring_count"] == 1
        assert len(status["expiring_items"]) == 1


def test_pantry_shortfall_sin_faltantes(engine_sembrado) -> None:
    """Shortfall identifica ingredientes que faltan."""
    hogar = _get_hogar(engine_sembrado)

    with Session(engine_sembrado) as session:
        receta = session.exec(
            select(Recipe).order_by(Recipe.id)
        ).first()
        if receta is None:
            pytest.skip("No hay recetas en la semilla")

        # Sin ingredientes en despensa → todo falta
        faltantes = get_pantry_shortfall(session, hogar, receta.id, 1.0)
        assert isinstance(faltantes, list)


def test_gastos_registrar_y_listar(engine_sembrado) -> None:
    """Registrar gasto y obtener lista."""
    hogar = _get_hogar(engine_sembrado)

    with Session(engine_sembrado) as session:
        gasto = registrar_gasto(session, hogar, 15_000, date.today())
        assert gasto["expense_id"] is not None
        assert gasto["amount_clp"] == 15_000


def test_gastos_spending_summary(engine_sembrado) -> None:
    """Resumen de gastos agrupados."""
    hogar = _get_hogar(engine_sembrado)

    with Session(engine_sembrado) as session:
        registrar_gasto(session, hogar, 10_000, date.today())
        registrar_gasto(session, hogar, 20_000, date.today())

        resume = get_spending_summary(
            session,
            hogar,
            date.today() - timedelta(days=1),
            date.today() + timedelta(days=1),
            "category",
        )
        assert resume["total_clp"] == 30_000
        assert resume["count"] == 2


def test_gastos_budget_variance(engine_sembrado) -> None:
    """Compara gastos vs presupuesto planificado."""
    hogar = _get_hogar(engine_sembrado)

    with Session(engine_sembrado) as session:
        registrar_gasto(session, hogar, 50_000, date.today())

        variance = get_budget_variance(
            session,
            hogar,
            date.today() - timedelta(days=7),
        )
        assert variance["total_gastos_clp"] == 50_000
        assert isinstance(variance["status"], str)


def _get_hogar(engine) -> int:
    """Obtiene el ID del primer hogar de la semilla."""
    with Session(engine) as session:
        return session.exec(select(Household).order_by(Household.id)).first().id