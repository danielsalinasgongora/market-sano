"""Refresco por URL fijada (get_product): ¿es estable y cuánto tarda?"""

import asyncio
import json
import sys
import time

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

IDX = sys.argv[1]
URLS = [
    ("jumbo", "https://www.jumbo.cl/palta-hass-jumbo-granel/p"),
    ("jumbo", "https://www.jumbo.cl/leche-entera-colun-caja-1-l-natural/p"),
    ("santaisabel", "https://www.sisa.cl/leche-entera-1-l-cuisine-and-co-1858321/p"),
    ("santaisabel", "https://www.sisa.cl/arroz-largo-fino-1-kg-cuisine-and-co-1845787/p"),
]


async def main():
    async with Client(StdioTransport("node", [IDX]), timeout=60) as c:
        for store, u in URLS:
            t0 = time.perf_counter()
            r = await c.call_tool(
                "get_product", {"store": store, "idOrUrl": u}, raise_on_error=False
            )
            ms = round((time.perf_counter() - t0) * 1000)
            txt = (
                json.dumps(r.structured_content, ensure_ascii=False)
                if r.structured_content
                else r.content[0].text
            )
            print(f"{store} {u} {ms} ms error={r.is_error}\n  {txt[:500]}\n")
            await asyncio.sleep(1.5)


asyncio.run(main())
