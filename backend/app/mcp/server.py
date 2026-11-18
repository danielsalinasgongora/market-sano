# SPDX-License-Identifier: GPL-3.0-or-later
"""Instancia FastMCP de Market Sano.

Pin `fastmcp<3` (pyproject): la línea 2.x es la estable; 3.x/4.x están en
desarrollo con cambios de ruptura (se re-evalúa en la Fase 4 del plan).
"""

from fastmcp import FastMCP

INSTRUCCIONES = (
    "Market Sano: planificador de comidas y compras para Chile, con "
    "presupuesto en CLP. En esta Fase 0 dispones de tools de lectura: "
    "get_household_context (configuración del hogar), search_recipes "
    "(búsqueda por texto y etiquetas) y get_pantry_status (despensa). "
    "Catálogo abierto: search_store_products busca en Jumbo/Santa Isabel/"
    "Unimarc y add_product_from_store agrega el resultado al catálogo; esta "
    "última escribe, así que llámala primero con dry_run=true, muestra la "
    "vista previa y repite con dry_run=false solo si el usuario confirma. "
    "Los datos viven en la base local del usuario; si la base está vacía, "
    "sugiere ejecutar `python -m app.seed` para crear datos de ejemplo."
)

mcp = FastMCP(
    name="Market Sano",
    instructions=INSTRUCCIONES,
)
