# SPDX-License-Identifier: GPL-3.0-or-later
"""PriceService: trazabilidad completa de precios (spec §0.6 y §3.5).

Modelo de fuentes (spec §3.5):
- `manual`: lo ingresa el usuario; confianza alta y no caduca por TTL.
- `live`: obtenido del conector en vivo; caduca según `PRICE_CACHE_TTL_HOURS`
  y su fuente efectiva pasa a `cached` cuando supera su vida útil.
- `cached`: valor guardado que ya expiró (o almacenado así por el conector
  al servir desde caché).

La resolución es siempre "el snapshot más reciente gana"; la degradación
live→cached se expone con `source_efectiva` + `is_stale` para que la UI
advierta la antigüedad (spec §0.6: un precio "cached" de hace 12 horas no
es lo mismo que uno "live").
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.models import PriceSnapshot, ProductCatalog
from app.models.enums import PriceConfidence, PriceSource
from app.settings import get_settings


@dataclass(frozen=True)
class PrecioResuelto:
    """Precio con su trazabilidad, listo para exponer por API/MCP."""

    snapshot: PriceSnapshot
    is_stale: bool
    age_hours: float
    source_efectiva: PriceSource
    # None = la del snapshot; el conector la baja a `low` si no pudo refrescar.
    confidence_efectiva: PriceConfidence | None = None

    def a_dict(self) -> dict[str, object]:
        return {
            "product_id": self.snapshot.product_id,
            "store_id": self.snapshot.store_id,
            "price_clp": self.snapshot.price_clp,
            "unit_price_clp": self.snapshot.unit_price_clp,  # PPUM (SERNAC, §7.3)
            "is_promotion": self.snapshot.is_promotion,
            "source": self.snapshot.source.value,
            "source_efectiva": self.source_efectiva.value,
            "confidence": self.snapshot.confidence.value,
            "confidence_efectiva": (self.confidence_efectiva or self.snapshot.confidence).value,
            "fetched_at": self.snapshot.fetched_at.isoformat(),
            "is_stale": self.is_stale,
            "age_hours": round(self.age_hours, 2),
        }


def registrar_snapshot(
    session: Session,
    *,
    product_id: int,
    store_id: str,
    price_clp: int,
    unit_price_clp: int,
    source: PriceSource,
    confidence: PriceConfidence,
    is_promotion: bool = False,
) -> PriceSnapshot:
    """Persiste un snapshot nuevo (lo usa la API manual y el conector, Task 9)."""
    if session.get(ProductCatalog, product_id) is None:
        raise ValueError(f"No existe el producto {product_id}.")
    if price_clp <= 0 or unit_price_clp <= 0:
        raise ValueError("price_clp y unit_price_clp (PPUM) deben ser positivos.")
    snapshot = PriceSnapshot(
        product_id=product_id,
        store_id=store_id,
        price_clp=price_clp,
        unit_price_clp=unit_price_clp,
        is_promotion=is_promotion,
        source=source,
        confidence=confidence,
    )
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)
    return snapshot


def registrar_precio_manual(
    session: Session,
    *,
    product_id: int,
    store_id: str,
    price_clp: int,
    unit_price_clp: int,
    is_promotion: bool = False,
) -> PriceSnapshot:
    """Precio manual del usuario: confianza alta (spec §3.5)."""
    return registrar_snapshot(
        session,
        product_id=product_id,
        store_id=store_id,
        price_clp=price_clp,
        unit_price_clp=unit_price_clp,
        source=PriceSource.manual,
        confidence=PriceConfidence.high,
        is_promotion=is_promotion,
    )


def get_latest_price(
    session: Session,
    *,
    product_id: int,
    store_id: str,
    ttl_hours: int | None = None,
) -> PrecioResuelto | None:
    """Snapshot más reciente del producto en la cadena, con trazabilidad.

    El TTL se usa para marcar `is_stale` y degradar la fuente efectiva de
    `live` a `cached`. Los precios manuales nunca caducan.
    """
    ttl = ttl_hours if ttl_hours is not None else get_settings().price_cache_ttl_hours
    snapshot = session.exec(
        select(PriceSnapshot)
        .where(PriceSnapshot.product_id == product_id)
        .where(PriceSnapshot.store_id == store_id)
        .order_by(PriceSnapshot.fetched_at.desc())
        .limit(1)
    ).first()
    if snapshot is None:
        return None

    fetched_at = snapshot.fetched_at
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=UTC)
    age_hours = (datetime.now(UTC) - fetched_at).total_seconds() / 3600

    is_stale = snapshot.source != PriceSource.manual and age_hours > ttl
    source_efectiva = snapshot.source
    if snapshot.source == PriceSource.live and is_stale:
        source_efectiva = PriceSource.cached

    return PrecioResuelto(
        snapshot=snapshot,
        is_stale=is_stale,
        age_hours=age_hours,
        source_efectiva=source_efectiva,
    )
