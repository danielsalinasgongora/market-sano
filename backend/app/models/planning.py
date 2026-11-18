# SPDX-License-Identifier: GPL-3.0-or-later
"""Planificación semanal, presupuestos y listas de compras (spec §3.4 y §3.5)."""

import uuid
from datetime import date, datetime

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.common import json_column, utcnow
from app.models.enums import ListStatus, MealSlot, PlanStatus


class MealPlan(SQLModel, table=True):
    """Plan semanal. Un plan por hogar y semana (spec §3.4)."""

    __tablename__ = "meal_plans"
    __table_args__ = (
        UniqueConstraint("household_id", "week_start", name="uq_meal_plans_household_week"),
    )

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="households.id", index=True)
    week_start: date
    budget_clp: int
    status: PlanStatus = Field(default=PlanStatus.draft)
    created_by: uuid.UUID | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow)
    confirmed_at: datetime | None = Field(default=None)


class MealPlanEntry(SQLModel, table=True):
    """Entrada de un plan: un slot de comida en una fecha.

    `recipe_id` es nullable para el modo "noche libre" (sobras o comida para
    llevar, contabilizada en el presupuesto vía `estimated_cost_clp`).
    Índice crítico de la spec §5: (plan_id, date).
    """

    __tablename__ = "meal_plan_entries"
    __table_args__ = (
        Index("ix_meal_plan_entries_plan_date", "plan_id", "date"),
        UniqueConstraint("plan_id", "date", "meal_slot", name="uq_meal_plan_entries_slot"),
    )

    id: int | None = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="meal_plans.id", index=True)
    date: date
    meal_slot: MealSlot
    recipe_id: int | None = Field(default=None, foreign_key="recipes.id", index=True)
    servings_multiplier: float = Field(default=1.0)
    sort_order: int = Field(default=0)
    label: str | None = Field(default=None, max_length=120)
    estimated_cost_clp: int | None = Field(default=None)


class BudgetSnapshot(SQLModel, table=True):
    """Estimación histórica de costo de un plan por cadena."""

    __tablename__ = "budget_snapshots"

    id: int | None = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="meal_plans.id", index=True)
    store_id: str = Field(max_length=64)
    total_clp: int
    breakdown: dict = Field(default_factory=dict, sa_column=json_column())
    fetched_at: datetime = Field(default_factory=utcnow)


class ShoppingList(SQLModel, table=True):
    """Lista de compras, generada desde un plan o manual."""

    __tablename__ = "shopping_lists"

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="households.id", index=True)
    plan_id: int | None = Field(default=None, foreign_key="meal_plans.id", index=True)
    name: str = Field(max_length=120)
    status: ListStatus = Field(default=ListStatus.active)
    created_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = Field(default=None)


class ShoppingListItem(SQLModel, table=True):
    """Ítem de una lista. Índice crítico de la spec §5: (list_id, checked)."""

    __tablename__ = "shopping_list_items"
    __table_args__ = (Index("ix_shopping_list_items_checked", "list_id", "checked"),)

    id: int | None = Field(default=None, primary_key=True)
    list_id: int = Field(foreign_key="shopping_lists.id", index=True)
    product_id: int = Field(foreign_key="product_catalog.id", index=True)
    required_quantity: float
    unit: str = Field(max_length=32)
    checked: bool = Field(default=False)
    actual_price_clp: int | None = Field(default=None)
    store_id: str | None = Field(default=None, max_length=64)
