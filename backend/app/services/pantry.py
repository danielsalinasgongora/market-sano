# SPDX-License-Identifier: GPL-3.0-or-later
"""Despensa: ítems, movimientos, shortfall y vencimientos (spec §3.3).

Reglas:
- Ajustar cantidad genera movimiento con delta y razón.
- `get_pantry_shortfall` calcula faltante para ingredientes requeridos.
- Ítems a vencer en N días aparecen en status.
"""

from datetime import date, timedelta
from typing import Any

from sqlmodel import Session, select

from app.models import PantryItem, PantryMovement, ProductCatalog, Recipe, RecipeIngredient
from app.models.enums import MovementReason


class PantryError(ValueError):
    """Error de despensa (mensaje accionable)."""


def ajustar_cantidad(
    session: Session,
    household_id: int,
    product_id: int,
    delta: float,
    reason: MovementReason,
    reference_id: str | None = None,
) -> dict[str, Any]:
    """Ajusta cantidad de un ítem y registra el movimiento."""
    item = session.exec(
        select(PantryItem).where(
            PantryItem.household_id == household_id,
            PantryItem.product_id == product_id,
        )
    ).first()

    if item is None:
        raise PantryError(f"No existe el producto {product_id} en tu despensa.")

    item.quantity += delta
    if item.quantity <= 0:
        item.quantity = 0

    movimiento = PantryMovement(
        pantry_item_id=item.id,
        delta=delta,
        reason=reason,
        reference_id=reference_id,
    )
    session.add(movimiento)
    session.add(item)
    session.commit()
    session.refresh(item)

    return {
        "product_id": product_id,
        "quantity": item.quantity,
        "unit": item.unit,
        "movement": {
            "delta": delta,
            "reason": reason.value,
            "reference_id": reference_id,
        },
    }


def obtener_despensa(
    session: Session, household_id: int, location: str | None = None
) -> list[dict[str, Any]]:
    """Lista items de despensa filtrados por ubicación opcional."""
    consulta = select(PantryItem).where(PantryItem.household_id == household_id)
    if location:
        from app.models.enums import PantryLocation
        try:
            loc = PantryLocation(location.lower())
            consulta = consulta.where(PantryItem.location == loc)
        except ValueError:
            pass

    items = session.exec(consulta.order_by(PantryItem.location, PantryItem.id)).all()
    resultado = []
    for item in items:
        producto = session.get(ProductCatalog, item.product_id)
        resultado.append({
            "product_id": item.product_id,
            "product_name": producto.canonical_name if producto else "Desconocido",
            "quantity": item.quantity,
            "unit": item.unit,
            "location": item.location.value,
            "purchased_at": item.purchased_at.isoformat() if item.purchased_at else None,
            "expires_at": item.expires_at.isoformat() if item.expires_at else None,
        })
    return resultado


def obtener_status(
    session: Session,
    household_id: int,
    expiring_within_days: int = 3,
) -> dict[str, Any]:
    """Estado de la despensa con items a vencer."""
    desde = date.today() + timedelta(days=expiring_within_days)
    items = obtener_despensa(session, household_id)

    vencen = [
        i for i in items
        if i["expires_at"] and date.fromisoformat(i["expires_at"]) <= desde
    ]

    total_items = len(items)
    total_qty = sum(i["quantity"] for i in items)

    return {
        "total_items": total_items,
        "total_quantity": total_qty,
        "expiring_within_days": expiring_within_days,
        "expiring_count": len(vencen),
        "expiring_items": vencen,
    }


def get_pantry_shortfall(
    session: Session,
    household_id: int,
    recipe_id: int,
    servings_multiplier: float = 1.0,
) -> list[dict[str, Any]]:
    """Calcula qué ingredientes faltan para una receta."""
    receta = session.get(Recipe, recipe_id)
    if receta is None:
        raise ValueError(f"No existe la receta {recipe_id}.")

    ingredientes = session.exec(
        select(RecipeIngredient)
        .where(RecipeIngredient.recipe_id == recipe_id)
        .order_by(RecipeIngredient.sort_order)
    ).all()

    falten: list[dict[str, Any]] = []
    for ing in ingredientes:
        producto = session.get(ProductCatalog, ing.product_id)
        if producto is None:
            continue

        requerido = ing.quantity * servings_multiplier

        item = session.exec(
            select(PantryItem).where(
                PantryItem.household_id == household_id,
                PantryItem.product_id == ing.product_id,
            )
        ).first()

        disponible = item.quantity if item else 0
        if disponible < requerido:
            falten.append({
                "product_id": ing.product_id,
                "product_name": producto.canonical_name,
                "required": requerido,
                "available": disponible,
                "shortfall": requerido - disponible,
                "unit": ing.unit,
            })

    return falten