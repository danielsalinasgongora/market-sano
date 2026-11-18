# SPDX-License-Identifier: GPL-3.0-or-later
"""Conector MCP falso (stdio) que imita a mcp-supermercados-cl en los tests.

Uso: python conector_falso.py <modo>   — modo: ok | error
"""

import sys

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

MODO = sys.argv[1] if len(sys.argv) > 1 else "ok"
mcp = FastMCP("conector-falso")

# url/sku → respuesta con la forma real del conector (ver spike T8)
PRODUCTOS = {
    "https://www.jumbo.cl/tomate-larga-vida-granel/p": {
        "sku": "261275-KG", "name": "Tomate Larga Vida Granel", "price": 995,
        "listPrice": 1290, "unitPrice": 1990, "unit": "kg",
    },
    "https://www.jumbo.cl/leche-entera-surlat-b-a-1l-1991554/p": {
        "sku": "1991554", "name": "Leche Surlat Entera 1 L", "price": 1000,
        "unitPrice": 1000, "unit": "lt",
    },
}
UNIMARC = [
    {"sku": "111", "name": "Arroz otra marca 1 Kg", "price": 1500, "unitPrice": 1500, "unit": "kg"},
    {"sku": "9411", "name": "Arroz Merkat G2 1 Kg", "price": 890, "unitPrice": 890, "unit": "kg"},
]


def _fallar_si_corresponde() -> None:
    if MODO == "error":
        raise ToolError("HTTP 503 en la cadena (simulado)")


@mcp.tool
def get_product(store: str, idOrUrl: str) -> dict:  # noqa: N803 (nombre del upstream)
    _fallar_si_corresponde()
    if idOrUrl not in PRODUCTOS:
        raise ToolError("No se encontró el recurso (HTTP 404).")
    return {"store": store, "url": idOrUrl, **PRODUCTOS[idOrUrl]}


@mcp.tool
def search_products(store: str, query: str, limit: int = 10) -> dict:
    _fallar_si_corresponde()
    return {"store": store, "query": query, "products": UNIMARC[:limit]}


if __name__ == "__main__":
    mcp.run(show_banner=False)
