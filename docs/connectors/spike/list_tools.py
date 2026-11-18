import asyncio
import json
import sys

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

IDX = sys.argv[1]


async def main():
    async with Client(StdioTransport("node", [IDX])) as c:
        for t in await c.list_tools():
            print("##", t.name)
        r = await c.call_tool("adapter_status", {})
        print(
            json.dumps(r.structured_content or [x.text for x in r.content], ensure_ascii=False)[
                :3000
            ]
        )


asyncio.run(main())
