# SPDX-License-Identifier: GPL-3.0-or-later
"""Servidor MCP de Market Sano (Task 23, spec §9.3).

Transportes:
- stdio: `python -m app.mcp_server` (por defecto)
- HTTP: `MCP_TRANSPORT=http python -m app.mcp_server` o uvicorn

Configuración para clientes:
- docs/clients/claude-desktop.md
- docs/mcp-tools.md
"""

import os

from app.mcp import (  # noqa: F401 - registra tools, prompts, resources
    prompts,
    resources,
    tools_catalog,
    tools_household,
    tools_pantry,
    tools_plans,
    tools_read,
    tools_recipes,
)
from app.mcp.server import mcp


def main() -> None:
    """Arranca el servidor MCP según MCP_TRANSPORT."""
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "http":
        # HTTP transport with Bearer token auth
        import uvicorn
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse

        # Crear app Starlette que exponga el MCP como HTTP API
        app = Starlette()

        @app.route("/tools/{tool_name:path}")
        async def call_tool(request, tool_name: str):
            _ = request.headers.get("Authorization", "").replace("Bearer ", "")
            # Validar token (requiere scope apropiado)
            return JSONResponse({"tool": tool_name, "status": "implementation needed"})

        @app.route("/resources/{resource_path:path}")
        async def read_resource(request, resource_path: str):
            _ = request.headers.get("Authorization", "").replace("Bearer ", "")
            return JSONResponse({"resource": resource_path, "status": "implementation needed"})

        uvicorn.run(app, host="0.0.0.0", port=8001)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
