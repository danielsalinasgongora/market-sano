# SPDX-License-Identifier: GPL-3.0-or-later
"""Conector de precios en vivo vía `mcp-supermercados-cl` (decisión T8).

El backend lanza el conector como subproceso local y le habla MCP por stdio
(`fastmcp.Client`). Solo se consultan productos con match fijado por cadena
(`product_store_matches`); nunca se adivina un producto por texto libre.

Prioridad (spec §3.5): live fresco → refresco live → caché/manual degradado.
Ante cualquier fallo del conector se devuelve el último precio conocido con
`confidence_efectiva=low` y una advertencia; nunca se propaga la excepción.
"""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from sqlmodel import Session, select

from app.models import ProductCatalog, ProductStoreMatch
from app.models.enums import PriceConfidence, PriceSource
from app.services.prices import PrecioResuelto, get_latest_price, registrar_snapshot
from app.settings import Settings

# Cadenas cuyo conector permite consultar un producto por URL (get_product).
# En el resto se busca por nombre y se elige el resultado con el SKU fijado.
CADENAS_CON_URL = {"jumbo", "santaisabel"}

# Unidad del PPUM que espera el catálogo según su unidad canónica.
UNIDAD_PPUM = {"g": "kg", "ml": "lt", "unidad": "un"}


class ErrorConector(Exception):
    """Fallo del conector o respuesta inutilizable (se degrada, no se propaga)."""


def ppum_catalogo(producto: ProductCatalog, unit_price: float, unit: str) -> int | None:
    """Convierte el PPUM de la cadena a la unidad del catálogo; None si no se puede."""
    if unit == UNIDAD_PPUM.get(producto.default_unit):
        return round(unit_price)
    if producto.default_unit == "unidad" and unit == "kg" and producto.unit_weight_g:
        return round(unit_price * producto.unit_weight_g / 1000)
    return None


def _datos(resultado: Any) -> dict[str, Any]:
    if resultado.is_error:
        texto = resultado.content[0].text if resultado.content else "error sin detalle"
        raise ErrorConector(texto[:300])
    if resultado.structured_content:
        return resultado.structured_content
    return json.loads(resultado.content[0].text)


def _cliente(settings: Settings) -> Client:
    """shortcut: un subproceso por consulta (~1 s extra); pasar a un cliente
    persistente si el refresco masivo lo hace lento."""
    comando, *args = settings.supermercados_command
    return Client(StdioTransport(comando, args), timeout=settings.supermercados_timeout_s)


async def buscar_productos(
    settings: Settings, store_id: str, query: str, limit: int = 10
) -> list[dict[str, Any]]:
    """Búsqueda passthrough en la cadena (T9b). Solo lectura; lanza ErrorConector."""
    if not settings.supermercados_enabled:
        raise ErrorConector(
            "El conector de supermercados está deshabilitado (SUPERMERCADOS_ENABLED=false)."
        )
    try:
        async with _cliente(settings) as c:
            datos = _datos(
                await c.call_tool(
                    "search_products",
                    {"store": store_id, "query": query, "limit": limit},
                    raise_on_error=False,
                )
            )
    except ErrorConector:
        raise
    except Exception as exc:  # subproceso caído, timeout: mensaje accionable
        raise ErrorConector(f"No se pudo consultar {store_id}: {exc}") from exc
    return datos.get("products", [])


async def _consultar(
    settings: Settings, store_id: str, match: ProductStoreMatch, query: str
) -> dict[str, Any]:
    """Precio actual del producto fijado por el match."""
    async with _cliente(settings) as c:
        if store_id in CADENAS_CON_URL:
            return _datos(
                await c.call_tool(
                    "get_product",
                    {"store": store_id, "idOrUrl": match.store_url},
                    raise_on_error=False,
                )
            )
        datos = _datos(
            await c.call_tool(
                "search_products",
                {"store": store_id, "query": query, "limit": 20},
                raise_on_error=False,
            )
        )
        for producto in datos.get("products", []):
            if producto.get("sku") == match.sku or producto.get("url") == match.store_url:
                return producto
        raise ErrorConector(f"El producto fijado (sku {match.sku}) ya no aparece en {store_id}.")


def _utc(momento: datetime) -> datetime:
    return momento if momento.tzinfo else momento.replace(tzinfo=UTC)


def _degradado(previo: PrecioResuelto | None) -> PrecioResuelto | None:
    # La palabra del usuario (manual) no se degrada; caché/live viejo sí.
    if previo is None or previo.snapshot.source == PriceSource.manual:
        return previo
    return replace(previo, confidence_efectiva=PriceConfidence.low)


def refrescar_precio(
    session: Session, settings: Settings, *, product_id: int, store_id: str
) -> tuple[PrecioResuelto | None, str | None]:
    """Último precio del producto, refrescándolo en vivo si hace falta.

    Devuelve (precio, advertencia). Solo llama al conector si está habilitado,
    hay match para la cadena y no existe un live dentro del TTL.
    """
    ttl = settings.price_cache_ttl_hours
    previo = get_latest_price(session, product_id=product_id, store_id=store_id, ttl_hours=ttl)
    match = session.exec(
        select(ProductStoreMatch).where(
            ProductStoreMatch.product_id == product_id, ProductStoreMatch.store_id == store_id
        )
    ).first()
    fresco = (
        previo is not None
        and previo.snapshot.source == PriceSource.live
        and not previo.is_stale
        # un match reemplazado (T9b) invalida el live del producto anterior
        and (match is None or _utc(previo.snapshot.fetched_at) >= _utc(match.matched_at))
    )
    if fresco or not settings.supermercados_enabled or match is None:
        return previo, None

    producto = session.get(ProductCatalog, product_id)
    try:
        datos = asyncio.run(_consultar(settings, store_id, match, producto.canonical_name))
        ppum = ppum_catalogo(producto, datos.get("unitPrice") or 0, datos.get("unit") or "")
        if not datos.get("price") or not ppum:
            raise ErrorConector(
                f"PPUM no convertible ({datos.get('unitPrice')}/{datos.get('unit')} "
                f"→ {producto.default_unit})."
            )
        registrar_snapshot(
            session,
            product_id=product_id,
            store_id=store_id,
            price_clp=int(datos["price"]),
            unit_price_clp=ppum,
            source=PriceSource.live,
            confidence=PriceConfidence.high,
            is_promotion=bool(datos.get("listPrice") and datos["listPrice"] > datos["price"]),
        )
    except Exception as exc:  # conector caído, timeout, respuesta rara: degradar
        motivo = f"No se pudo actualizar el precio en {store_id}: {exc}"
        return _degradado(previo), motivo

    return get_latest_price(session, product_id=product_id, store_id=store_id, ttl_hours=ttl), None
