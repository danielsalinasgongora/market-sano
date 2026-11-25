# SPDX-License-Identifier: GPL-3.0-or-later
"""Gastos reales + varianza + resúmenes (spec §3.6).

Reglas:
- `record_expense` cierra el ciclo presupuesto → compra → gasto.
- `get_budget_variance` compara presupuestoado vs real del período.
- `get_spending_summary` agrupa por categoría/cadena.
"""

from datetime import date
from typing import Any

from sqlmodel import Session, select

from app.models import Expense, ExpenseCategory, ExpenseItem, Household, MealPlan


class ExpenseError(ValueError):
    """Error de gasto (mensaje accionable)."""


def registrar_gasto(
    session: Session,
    household_id: int,
    amount_clp: int,
    date_spent: date | None = None,
    store_id: str | None = None,
    category_id: int | None = None,
    notes: str | None = None,
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Registra un gasto real del hogar."""
    if amount_clp <= 0:
        raise ExpenseError("amount_clp debe ser mayor que 0.")

    gasto = Expense(
        household_id=household_id,
        amount_clp=amount_clp,
        date=date_spent or date.today(),
        store_id=store_id,
        category_id=category_id,
        notes=notes,
    )
    session.add(gasto)
    session.flush()

    if items:
        for item in items:
            detalle = ExpenseItem(
                expense_id=gasto.id,
                product_id=item["product_id"],
                quantity=item.get("quantity", 1),
                unit=item.get("unit"),
                unit_price_clp=item.get("unit_price_clp", item.get("quantity", 1)),
            )
            session.add(detalle)

    session.commit()
    session.refresh(gasto)
    return {
        "expense_id": gasto.id,
        "household_id": household_id,
        "amount_clp": gasto.amount_clp,
        "date": gasto.date.isoformat(),
        "store_id": gasto.store_id,
        "category_id": gasto.category_id,
        "notes": gasto.notes,
    }


def obtener_gastos(
    session: Session, household_id: int, start_date: date | None = None
) -> list[dict[str, Any]]:
    """Lista gastos del hogar, opcionalmente desde una fecha."""
    consulta = select(Expense).where(Expense.household_id == household_id)
    if start_date:
        consulta = consulta.where(Expense.date >= start_date)

    gastos = session.exec(consulta.order_by(Expense.date.desc(), Expense.id)).all()
    resultado = []
    for g in gastos:
        categoria = session.get(ExpenseCategory, g.category_id) if g.category_id else None
        item_count = session.exec(
            select(ExpenseItem)
            .where(ExpenseItem.expense_id == g.id)
        ).count()
        resultado.append({
            "expense_id": g.id,
            "amount_clp": g.amount_clp,
            "date": g.date.isoformat(),
            "store_id": g.store_id,
            "category": categoria.name if categoria else None,
            "item_count": item_count,
        })
    return resultado


def get_spending_summary(
    session: Session,
    household_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    group_by: str = "category",
) -> dict[str, Any]:
    """Resumen de gastos agrupados por categoría o cadena."""
    consulta = select(Expense).where(Expense.household_id == household_id)
    if start_date:
        consulta = consulta.where(Expense.date >= start_date)
    if end_date:
        consulta = consulta.where(Expense.date <= end_date)

    gastos = session.exec(consulta).all()

    total_clp = sum(g.amount_clp for g in gastos)
    por_categoria: dict[str, int] = {}
    por_cadena: dict[str, int] = {}

    for g in gastos:
        categoria = session.get(ExpenseCategory, g.category_id) if g.category_id else None
        cat_key = (categoria.name if categoria else "Sin categoría")
        por_categoria[cat_key] = por_categoria.get(cat_key, 0) + g.amount_clp

        cad_key = g.store_id or "desconocido"
        por_cadena[cad_key] = por_cadena.get(cad_key, 0) + g.amount_clp

    if group_by == "category":
        grouped = dict(sorted(por_categoria.items(), key=lambda x: -x[1]))
    else:
        grouped = dict(sorted(por_cadena.items(), key=lambda x: -x[1]))

    return {
        "total_clp": total_clp,
        "grouped": grouped,
        "count": len(gastos),
    }


def get_budget_variance(
    session: Session,
    household_id: int,
    period_start: date,
    period_end: date | None = None,
) -> dict[str, Any]:
    """Compara gastos reales vs presupuesto planificado."""
    if period_end is None:
        period_end = date.today()

    gastos = session.exec(
        select(Expense)
        .where(
            Expense.household_id == household_id,
            Expense.date >= period_start,
            Expense.date <= period_end,
        )
    ).all()

    total_gastos_clp = sum(g.amount_clp for g in gastos)

    planes = session.exec(
        select(MealPlan)
        .where(
            MealPlan.household_id == household_id,
            MealPlan.week_start <= period_end,
        )
    ).all()
    total_presupuesto_clp = sum(p.budget_clp for p in planes)

    variance = total_presupuesto_clp - total_gastos_clp

    return {
        "total_gastos_clp": total_gastos_clp,
        "total_presupuesto_clp": total_presupuesto_clp,
        "variance_clp": variance,
        "status": "under" if variance >= 0 else "over",
    }