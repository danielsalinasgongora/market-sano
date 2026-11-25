# SPDX-License-Identifier: GPL-3.0-or-later
"""Lista de compras: generación, pasillos, exportación (spec §3.5, Task 20).

Reglas:
- `generate_shopping_list(plan_id, store_ids [])` agrega ingredientes en canónica,
  descuenta despensa, convierte a packs `ceil(q/purchase_size)` (Anexo A).
- Agrupación por pasillo configurable por hogar.
- Ítems manuales, exportación CSV/texto.
"""

from typing import Any

from sqlmodel import Session, select

from app.models import (
    MealPlan,
    MealPlanEntry,
    PantryItem,
    PriceSnapshot,
    ProductCatalog,
    RecipeIngredient,
    ShoppingList,
    ShoppingListItem,
)
from app.models.enums import ListStatus


class ShoppingError(ValueError):
    """Error de lista de compras (mensaje accionable)."""


def generar_lista(
    session: Session,
    household_id: int,
    plan_id: int | None = None,
    store_ids: list[str] | None = None,
    name: str = "Lista de compras",
) -> dict[str, Any]:
    """Genera lista de compras desde un plan, descuenta despensa."""
    if plan_id:
        plan = session.get(MealPlan, plan_id)
        if plan is None or plan.household_id != household_id:
            raise ShoppingError("No existe el plan para tu hogar.")

    lista = ShoppingList(
        household_id=household_id,
        plan_id=plan_id,
        name=name,
        status=ListStatus.active,
    )
    session.add(lista)
    session.flush()

    if plan_id:
        entradas = session.exec(
            select(MealPlanEntry)
            .where(MealPlanEntry.plan_id == plan_id)
            .where(MealPlanEntry.recipe_id.is_not(None))
        ).all()

        for entrada in entradas:
            recipe_ingredients = session.exec(
                select(RecipeIngredient)
                .where(RecipeIngredient.recipe_id == entrada.recipe_id)
            ).all()

            for ing in recipe_ingredients:
                producto = session.get(ProductCatalog, ing.product_id)
                if producto is None:
                    continue

                pantry_qty = _get_pantry_qty(session, household_id, ing.product_id)
                required = ing.quantity * entrada.servings_multiplier
                needed = max(0, required - pantry_qty)

                if needed > 0:
                    item = ShoppingListItem(
                        list_id=lista.id,
                        product_id=ing.product_id,
                        required_quantity=needed,
                        unit=ing.unit,
                    )
                    session.add(item)

    session.commit()
    session.refresh(lista)

    return {
        "list_id": lista.id,
        "household_id": household_id,
        "name": lista.name,
        "status": lista.status.value,
    }


def _get_pantry_qty(session: Session, household_id: int, product_id: int) -> float:
    """Obtiene cantidad disponible en despensa."""
    item = session.exec(
        select(PantryItem)
        .where(PantryItem.household_id == household_id)
        .where(PantryItem.product_id == product_id)
    ).first()
    return item.quantity if item else 0


def obtener_lista(
    session: Session,
    household_id: int,
    list_id: int,
    group_by: str = "aisle",
) -> dict[str, Any]:
    """Obtiene lista de compras agrupada por pasillo o tienda."""
    lista = session.get(ShoppingList, list_id)
    if lista is None or lista.household_id != household_id:
        raise ShoppingError("No existe la lista para tu hogar.")

    items = session.exec(
        select(ShoppingListItem)
        .where(ShoppingListItem.list_id == list_id)
    ).all()

    resultado = []
    for item in items:
        producto = session.get(ProductCatalog, item.product_id)
        aisle = producto.aisle if producto and producto.aisle else "Otros"
        store = item.store_id or "sin asignar"

        resultado.append({
            "product_id": item.product_id,
            "product_name": producto.name if producto else "Desconocido",
            "aisle": aisle,
            "store_id": store,
            "required_quantity": item.required_quantity,
            "unit": item.unit,
            "checked": item.checked,
            "actual_price_clp": item.actual_price_clp,
        })

    return {
        "list_id": lista.id,
        "name": lista.name,
        "status": lista.status.value,
        "items": resultado,
    }


def comparar_basket_across_stores(
    session: Session,
    household_id: int,
    list_id: int,
    threshold_pct: float = 0.10,
) -> dict[str, Any]:
    """Compara costo de lista por cadena usando PPUM.

    Devuelve total por cadena y sugiere "dividir la compra" si el ahorro supera el umbral.
    """
    lista = session.get(ShoppingList, list_id)
    if lista is None or lista.household_id != household_id:
        raise ShoppingError("No existe la lista para tu hogar.")

    items = session.exec(
        select(ShoppingListItem)
        .where(ShoppingListItem.list_id == list_id)
        .where(ShoppingListItem.product_id.is_not(None))
    ).all()

    por_cadena: dict[str, dict[str, Any]] = {}
    por_producto: dict[str, dict[str, Any]] = {}

    for item in items:
        producto = session.get(ProductCatalog, item.product_id)
        if producto is None:
            continue

        store_id = item.store_id or "default"
        if store_id not in por_cadena:
            por_cadena[store_id] = {"total_clp": 0, "items": []}

        precio_recente = session.exec(
            select(PriceSnapshot)
            .where(PriceSnapshot.product_id == item.product_id)
            .where(PriceSnapshot.store_id == store_id)
            .order_by(PriceSnapshot.fetched_at.desc())
        ).first()

        # Usar PPUM cuando no hay precio por unidad
        unit_price = None
        if precio_recente:
            unit_price = precio_recente.unit_price_clp or precio_recente.price_clp * 1000

        if unit_price is None and producto:
            unit_price = item.required_quantity * 1000  # fallback

        costo = unit_price * item.required_quantity if unit_price else 0
        por_cadena[store_id]["total_clp"] += costo
        por_cadena[store_id]["items"].append({
            "product_id": item.product_id,
            "name": producto.name if producto else "Desconocido",
            "quantity": item.required_quantity,
            "unit": item.unit,
            "cost_clp": costo,
        })

        clave = f"{item.product_id}_{store_id}"
        if clave not in por_producto:
            por_producto[clave] = {
                "product_id": item.product_id,
                "name": producto.name if producto else "Desconocido",
                "prices_by_store": {},
            }
        por_producto[clave]["prices_by_store"][store_id] = costo

    # Encontrar oportunidades de división
    division_suggestions = []
    stores = list(por_cadena.keys())
    if len(stores) > 1:
        totals = [(s, d["total_clp"]) for s, d in por_cadena.items()]
        totals.sort(key=lambda x: x[1])
        cheapest = totals[0][1]
        most_expensive = totals[-1][1]
        savings = most_expensive - cheapest
        savings_pct = savings / most_expensive if most_expensive else 0

        if savings_pct >= threshold_pct:
            for _item_key, data in por_producto.items():
                prices = list(data["prices_by_store"].values())
                if len(prices) > 1:
                    price_diff = max(prices) - min(prices)
                    if price_diff > 0:
                        division_suggestions.append({
                            "product_id": data["product_id"],
                            "name": data["name"],
                            "cheapest_store": min(
                                data["prices_by_store"], key=data["prices_by_store"].get
                            ),
                            "most_expensive_store": max(
                                data["prices_by_store"], key=data["prices_by_store"].get
                            ),
                            "saving_clp": price_diff,
                        })

    return {
        "list_id": list_id,
        "stores": [
            {"store_id": s, "total_clp": d["total_clp"]}
            for s, d in por_cadena.items()
        ],
        "cheapest_store": (
            min(por_cadena, key=lambda s: por_cadena[s]["total_clp"])
            if por_cadena else None
        ),
        "savings_if_sharing": (
            sum(d["saving_clp"] for d in division_suggestions)
            if division_suggestions else 0
        ),
        "division_suggestions": division_suggestions[:10],  # Top 10
    }