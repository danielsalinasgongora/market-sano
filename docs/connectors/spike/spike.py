"""Spike T8: 20 productos del catálogo x 3 cadenas vía search_products (stdio MCP)."""

import asyncio
import json
import sys
import time

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

IDX, OUT = sys.argv[1], sys.argv[2]
STORES = ["jumbo", "santaisabel", "unimarc"]
# canonical_name -> query (None = mismo nombre)
PRODUCTOS = {
    "palta": "palta hass",
    "tomate": None,
    "cebolla": None,
    "papa": None,
    "zanahoria": None,
    "choclo": None,
    "carne molida de vacuno": "carne molida",
    "pollo": "pollo entero",
    "merluza": None,
    "atún": "atún lomitos",
    "huevo": "huevos",
    "leche": "leche entera",
    "mantequilla": None,
    "porotos": "porotos tórtola",
    "lentejas": None,
    "arroz": "arroz grado 2",
    "fideos": "fideos spaghetti",
    "aceite": "aceite vegetal",
    "harina": "harina sin polvos",
    "azúcar": None,
}


def parse(r):
    if r.structured_content:
        return r.structured_content
    return json.loads(r.content[0].text)


async def main():
    out = []
    async with Client(StdioTransport("node", [IDX]), timeout=60) as c:
        for store in STORES:
            for canon, q in PRODUCTOS.items():
                q = q or canon
                t0 = time.perf_counter()
                try:
                    data = parse(
                        await c.call_tool(
                            "search_products",
                            {"store": store, "query": q, "limit": 10},
                            raise_on_error=False,
                        )
                    )
                    err = None
                except Exception as e:  # registrar el fallo, no abortar el spike
                    data, err = None, repr(e)
                ms = round((time.perf_counter() - t0) * 1000)
                out.append(
                    {
                        "store": store,
                        "canonical": canon,
                        "query": q,
                        "ms": ms,
                        "error": err,
                        "data": data,
                    }
                )
                n = len((data or {}).get("products", [])) if isinstance(data, dict) else 0
                print(f"{store:12} {canon:24} {ms:6} ms  n={n} {err or ''}", flush=True)
                await asyncio.sleep(1.5)  # ritmo humano
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


asyncio.run(main())
