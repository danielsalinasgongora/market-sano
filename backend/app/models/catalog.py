# SPDX-License-Identifier: GPL-3.0-or-later
"""Catálogo de productos, conectores y precios (spec §3.5)."""

from datetime import datetime

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.common import json_column, utcnow
from app.models.enums import PriceConfidence, PriceSource


class ProductCatalog(SQLModel, table=True):
    """Producto normalizado del catálogo interno.

    `default_unit` es la unidad canónica (g, ml, unidad). `purchase_size`
    es el tamaño del pack de compra en unidad canónica (Anexo A).
    `unit_weight_g` (opcional): peso medio de una unidad, para productos que
    el catálogo cuenta por unidad pero las cadenas venden a granel por kg.
    """

    __tablename__ = "product_catalog"

    id: int | None = Field(default=None, primary_key=True)
    canonical_name: str = Field(unique=True, index=True, max_length=200)
    category: str = Field(index=True, max_length=100)
    default_unit: str = Field(max_length=32)
    purchase_unit: str | None = Field(default=None, max_length=64)
    purchase_size: float | None = Field(default=None)
    aliases: list[str] = Field(default_factory=list, sa_column=json_column())
    unit_weight_g: float | None = Field(default=None)


class ProductStoreMatch(SQLModel, table=True):
    """Producto del catálogo ↔ producto concreto de una cadena (spike T8).

    El refresco live (T9) consulta `store_url` (o busca por `sku` donde la
    cadena no permite consultar por URL). Un match por (producto, cadena).
    """

    __tablename__ = "product_store_matches"
    __table_args__ = (
        UniqueConstraint(
            "product_id", "store_id", name="uq_product_store_matches_product_store"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product_catalog.id", ondelete="CASCADE")
    store_id: str = Field(max_length=64)
    store_url: str = Field(max_length=500)
    sku: str | None = Field(default=None, max_length=64)
    matched_at: datetime = Field(default_factory=utcnow)


class StoreConnector(SQLModel, table=True):
    """Registro de cadenas/conectores de supermercado (ej. "jumbo")."""

    __tablename__ = "store_connectors"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, max_length=64)
    type: str = Field(max_length=64)
    enabled: bool = Field(default=False)
    config: dict = Field(default_factory=dict, sa_column=json_column())


class PriceSnapshot(SQLModel, table=True):
    """Precio de un producto en una cadena, con trazabilidad completa.

    `unit_price_clp` es el PPUM, obligatorio por normativa SERNAC (spec §7.3),
    expresado según el `default_unit` del producto: g → CLP/kg, ml → CLP/L,
    unidad → CLP/unidad.
    Índice crítico de la spec §5: (product_id, store_id, fetched_at).
    Nota: el índice es ascendente plano; el rango de consulta típico
    (`WHERE product_id=? AND store_id=? ORDER BY fetched_at DESC LIMIT 1`)
    se resuelve recorriéndolo en reverso, y SQLite puede reflejarlo
    (un índice con expresión `desc()` no se puede reflejar ni comparar).
    """

    __tablename__ = "price_snapshots"
    __table_args__ = (
        Index("ix_price_snapshots_lookup", "product_id", "store_id", "fetched_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product_catalog.id", index=True)
    store_id: str = Field(max_length=64)
    price_clp: int
    unit_price_clp: int
    is_promotion: bool = Field(default=False)
    source: PriceSource
    confidence: PriceConfidence
    fetched_at: datetime = Field(default_factory=utcnow, index=True)
