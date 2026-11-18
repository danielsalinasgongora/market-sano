# SPDX-License-Identifier: GPL-3.0-or-later
"""Catálogo abierto (decisión D8, Task 9b): dar de alta en el catálogo un
producto encontrado en una cadena y fijar su match para el refresco live (T9).

El humano/agente elige el resultado de la búsqueda; aquí no hay auto-match.
`dry_run=True` (por defecto) devuelve la vista previa sin escribir.
"""

import re
from typing import Any

from sqlmodel import Session, func, select

from app.models import ProductCatalog, ProductStoreMatch
from app.models.common import utcnow

# Unidad del PPUM del conector → unidad canónica del catálogo.
UNIDAD_CANONICA = {"kg": "g", "lt": "ml", "un": "unidad"}

# Tamaño de pack en el nombre ("Leche Entera 1 L", "Arroz 1 kg", "Huevos 20 un.").
_TAMANO = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(kg|kilos?|g|gr|grs|l|lt|lts|litros?|ml|cc|un|unid|unidades)\b\.?",
    re.IGNORECASE,
)
_FACTOR = {  # unidad del nombre → (unidad canónica, factor)
    "kg": ("g", 1000), "kilo": ("g", 1000), "kilos": ("g", 1000),
    "g": ("g", 1), "gr": ("g", 1), "grs": ("g", 1),
    "l": ("ml", 1000), "lt": ("ml", 1000), "lts": ("ml", 1000),
    "litro": ("ml", 1000), "litros": ("ml", 1000),
    "ml": ("ml", 1), "cc": ("ml", 1),
    "un": ("unidad", 1), "unid": ("unidad", 1), "unidades": ("unidad", 1),
}


class AltaInvalida(ValueError):
    """Datos de alta inconsistentes (mensaje accionable para el usuario)."""


def inferir_pack(nombre: str, unidad_canonica: str) -> tuple[str | None, float | None]:
    """(purchase_unit, purchase_size) desde el nombre, si es coherente con la unidad."""
    for cantidad, unidad in reversed(_TAMANO.findall(nombre)):
        canonica, factor = _FACTOR[unidad.lower()]
        if canonica == unidad_canonica:
            return f"{cantidad} {unidad}", float(cantidad.replace(",", ".")) * factor
    return None, None


def alta_desde_cadena(
    session: Session,
    *,
    store_id: str,
    store_url: str,
    sku: str | None,
    store_product_name: str,
    unit: str,
    canonical_name: str,
    category: str = "otros",
    product_id: int | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Crea o vincula un producto del catálogo y fija su match en la cadena."""
    if unit not in UNIDAD_CANONICA:
        raise AltaInvalida(f"unit debe ser kg, lt o un (el `unit` del resultado); llegó {unit!r}.")
    nombre = canonical_name.strip().lower()
    if not nombre:
        raise AltaInvalida("canonical_name no puede estar vacío.")

    if product_id is not None:
        producto = session.get(ProductCatalog, product_id)
        if producto is None:
            raise AltaInvalida(f"No existe el producto {product_id}.")
    else:
        producto = session.exec(
            select(ProductCatalog).where(func.lower(ProductCatalog.canonical_name) == nombre)
        ).first()

    canonica = UNIDAD_CANONICA[unit]
    if producto is not None:
        accion = "vincular"
        granel_ok = producto.default_unit == "unidad" and unit == "kg" and producto.unit_weight_g
        if producto.default_unit != canonica and not granel_ok:
            raise AltaInvalida(
                f"'{producto.canonical_name}' se mide en {producto.default_unit} y el producto de "
                f"{store_id} se vende por {unit}: no se puede comparar su PPUM."
            )
    else:
        accion = "crear"
        compra, tamano = inferir_pack(store_product_name, canonica)
        producto = ProductCatalog(
            canonical_name=nombre, category=category.strip().lower() or "otros",
            default_unit=canonica, purchase_unit=compra, purchase_size=tamano, aliases=[],
        )

    match = None
    if producto.id is not None:
        match = session.exec(
            select(ProductStoreMatch).where(
                ProductStoreMatch.product_id == producto.id, ProductStoreMatch.store_id == store_id
            )
        ).first()

    vista = {
        "dry_run": dry_run,
        "accion": accion,
        "match": "reemplazar" if match else "crear",
        "producto": {
            "product_id": producto.id,
            "canonical_name": producto.canonical_name,
            "category": producto.category,
            "default_unit": producto.default_unit,
            "purchase_unit": producto.purchase_unit,
            "purchase_size": producto.purchase_size,
        },
        "store": {"store_id": store_id, "store_url": store_url, "sku": sku,
                  "name": store_product_name},
    }
    if dry_run:
        return vista

    session.add(producto)
    session.flush()
    if match is None:
        match = ProductStoreMatch(product_id=producto.id, store_id=store_id, store_url=store_url)
    match.store_url, match.sku, match.matched_at = store_url, sku, utcnow()
    session.add(match)
    session.commit()
    vista["producto"]["product_id"] = producto.id
    return vista
