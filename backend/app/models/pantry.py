# SPDX-License-Identifier: GPL-3.0-or-later
"""Inventario / despensa (spec §3.3)."""

from datetime import date, datetime

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

from app.models.common import utcnow
from app.models.enums import MovementReason, PantryLocation


class PantryItem(SQLModel, table=True):
    """Ítem en despensa. Índice crítico de la spec §5: (household_id, product_id)."""

    __tablename__ = "pantry_items"
    __table_args__ = (Index("ix_pantry_items_lookup", "household_id", "product_id"),)

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="households.id", index=True)
    product_id: int = Field(foreign_key="product_catalog.id", index=True)
    quantity: float
    unit: str = Field(max_length=32)
    location: PantryLocation = Field(default=PantryLocation.alacena)
    purchased_at: date | None = Field(default=None)
    expires_at: date | None = Field(default=None, index=True)


class PantryMovement(SQLModel, table=True):
    """Movimiento de stock: cada cambio de cantidad deja rastro auditable."""

    __tablename__ = "pantry_movements"

    id: int | None = Field(default=None, primary_key=True)
    pantry_item_id: int = Field(foreign_key="pantry_items.id", index=True)
    delta: float
    reason: MovementReason
    reference_id: str | None = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=utcnow)
