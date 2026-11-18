# SPDX-License-Identifier: GPL-3.0-or-later
"""Gastos reales del hogar (spec §3.6)."""

from datetime import date, datetime

from sqlmodel import Field, SQLModel

from app.models.common import utcnow


class ExpenseCategory(SQLModel, table=True):
    """Categoría de gasto (sementada con valores por defecto)."""

    __tablename__ = "expense_categories"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, max_length=120)


class Expense(SQLModel, table=True):
    """Gasto real registrado: cierra el ciclo presupuesto → compra → gasto."""

    __tablename__ = "expenses"

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="households.id", index=True)
    store_id: str | None = Field(default=None, max_length=64)
    amount_clp: int
    date: date
    category_id: int | None = Field(default=None, foreign_key="expense_categories.id", index=True)
    notes: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)


class ExpenseItem(SQLModel, table=True):
    """Desglose opcional de un gasto por producto (para PPUM y analytics)."""

    __tablename__ = "expense_items"

    id: int | None = Field(default=None, primary_key=True)
    expense_id: int = Field(foreign_key="expenses.id", index=True)
    product_id: int = Field(foreign_key="product_catalog.id", index=True)
    quantity: float
    unit: str | None = Field(default=None, max_length=32)
    unit_price_clp: int
