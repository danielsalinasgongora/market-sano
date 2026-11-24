# SPDX-License-Identifier: GPL-3.0-or-later
"""Servidor MCP de Market Sano.

Mismo código que la API, distinto entrypoint (spec §9.3): la API corre con
`uvicorn app.main:app`; este módulo expone el servidor MCP por stdio:

    python -m app.mcp_server

La configuración para clientes locales (Claude Desktop, Cursor) está en
docs/clients/claude-desktop.md, y el contrato de cada tool en
docs/mcp-tools.md.
"""

from app.mcp import (  # noqa: F401 - registra tools
    tools_catalog,
    tools_household,
    tools_plans,
    tools_read,
    tools_recipes,
)
from app.mcp.server import mcp


def main() -> None:
    """Arranca el servidor MCP (transporte stdio por defecto)."""
    mcp.run()


if __name__ == "__main__":
    main()
