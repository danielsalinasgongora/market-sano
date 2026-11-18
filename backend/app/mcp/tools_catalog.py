# SPDX-License-Identifier: GPL-3.0-or-later
"""Tools MCP del catálogo abierto (Task 9b, decisión D8).

`search_store_products` es solo lectura. `add_product_from_store` escribe en el
catálogo, por eso usa `dry_run=True` por defecto (spec §2.2): primero se
muestra la vista previa al usuario y solo con su confirmación se repite con
`dry_run=False`.
"""

from typing import Annotated, Any

from fastmcp.exceptions import ToolError
from sqlmodel import Session

from app.connectors.supermercados_cl import ErrorConector, buscar_productos
from app.mcp.db import mcp_engine
from app.mcp.server import mcp
from app.services.catalogo_abierto import AltaInvalida, alta_desde_cadena
from app.settings import get_settings


@mcp.tool
async def search_store_products(
    query: Annotated[str, 'Texto de búsqueda, ej. "leche descremada"'],
    store_id: Annotated[str, "Cadena: jumbo | santaisabel | unimarc"] = "jumbo",
    limit: Annotated[int, "Máximo de resultados (1-50)"] = 10,
) -> list[dict[str, Any]]:
    """Busca productos directamente en un supermercado (no escribe nada).

    Cada resultado trae name, brand, price, unitPrice + unit (PPUM por kg/lt/un),
    url y sku. Para agregar uno al catálogo, pasa sus campos a
    add_product_from_store."""
    try:
        return await buscar_productos(get_settings(), store_id, query, max(1, min(limit, 50)))
    except ErrorConector as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool
def add_product_from_store(
    store_id: Annotated[str, "Cadena del resultado elegido"],
    store_url: Annotated[str, "`url` del resultado elegido"],
    store_product_name: Annotated[str, "`name` del resultado elegido"],
    unit: Annotated[str, "`unit` del resultado: kg | lt | un"],
    canonical_name: Annotated[str, 'Nombre en el catálogo del hogar, ej. "leche descremada"'],
    sku: Annotated[str | None, "`sku` del resultado"] = None,
    category: Annotated[str, "Categoría del catálogo (verduras, lácteos, despensa…)"] = "otros",
    product_id: Annotated[int | None, "Vincular a un producto existente en vez de crear"] = None,
    dry_run: Annotated[bool, "true (defecto): solo vista previa; false: escribe"] = True,
) -> dict[str, Any]:
    """Da de alta en el catálogo un producto encontrado con search_store_products
    (o lo vincula a uno existente) y fija su match para que su precio se
    actualice en vivo. Con dry_run=true devuelve la vista previa sin escribir:
    muéstrala al usuario y repite con dry_run=false solo si la confirma."""
    with Session(mcp_engine()) as session:
        try:
            return alta_desde_cadena(
                session, store_id=store_id, store_url=store_url, sku=sku,
                store_product_name=store_product_name, unit=unit,
                canonical_name=canonical_name, category=category,
                product_id=product_id, dry_run=dry_run,
            )
        except AltaInvalida as exc:
            raise ToolError(str(exc)) from exc
