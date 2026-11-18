# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests del servidor MCP de Fase 0 contra la migración real y la semilla.

Usa el cliente in-memory de FastMCP: valida el protocolo MCP completo
(list_tools, call_tool, read_resource) sin red.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.exceptions import ToolError
from sqlalchemy import Engine
from sqlmodel import Session

from app.mcp import tools_read  # noqa: F401 - registra tools/resources al importar
from app.mcp.db import set_mcp_engine
from app.mcp.server import mcp
from app.seed import seed

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _data(resultado: Any) -> Any:
    """Contenido de la tool como JSON nativo.

    El campo estructurado (`.data`) envuelve las salidas tipo lista en
    modelos de pydantic con formas que cambian entre versiones de FastMCP;
    el texto JSON serializado es el contrato estable del protocolo.
    """
    for bloque in getattr(resultado, "content", []):
        texto = getattr(bloque, "text", None)
        if texto:
            return json.loads(texto)
    data = getattr(resultado, "data", None)
    if data is not None and hasattr(data, "root"):
        data = data.root
    return data


@pytest.fixture()
def mcp_seeded(migrated_engine: Engine) -> Any:
    """Servidor MCP apuntando a una BD migrada y sembrada."""
    with Session(migrated_engine) as session:
        seed(session)
    set_mcp_engine(migrated_engine)
    yield mcp
    set_mcp_engine(None)


def test_el_servidor_expone_las_tools_de_fase_0(mcp_seeded: Any) -> None:
    async def escenario() -> None:
        async with Client(mcp) as cliente:
            herramientas = await cliente.list_tools()
            nombres = {h.name for h in herramientas}
            assert {"get_household_context", "search_recipes", "get_pantry_status"} <= nombres

            # El template household://{id}/context aparece al listar plantillas.
            plantillas = await cliente.list_resource_templates()
            uris = {p.uriTemplate for p in plantillas}
            assert "household://{id}/context" in uris

    asyncio.run(escenario())


def test_get_household_context_devuelve_el_hogar_sembrado(mcp_seeded: Any) -> None:
    async def escenario() -> None:
        async with Client(mcp) as cliente:
            resultado = await cliente.call_tool("get_household_context", {})
            data = _data(resultado)
            assert data["name"] == "Mi Hogar"
            assert data["currency"] == "CLP"
            assert data["weekly_budget_clp"] == 45000
            assert data["default_store"] == "jumbo"
            assert data["dietary_restrictions"] == []

    asyncio.run(escenario())


def test_get_household_context_con_id_inexistente_es_error_accionable(mcp_seeded: Any) -> None:
    async def escenario() -> None:
        async with Client(mcp) as cliente:
            with pytest.raises(ToolError):
                await cliente.call_tool("get_household_context", {"household_id": 999})

    asyncio.run(escenario())


def test_search_recipes_por_texto_y_por_tags(mcp_seeded: Any) -> None:
    async def escenario() -> None:
        async with Client(mcp) as cliente:
            # Por texto: título o descripción, insensible a mayúsculas.
            resultado = await cliente.call_tool("search_recipes", {"query": "cazuela"})
            titulos = {r["title"] for r in _data(resultado)}
            assert "Cazuela de vacuno" in titulos

            # Por tags con semántica AND (spec §3.2).
            resultado = await cliente.call_tool(
                "search_recipes", {"tags": ["chilena", "guiso"]}
            )
            data = _data(resultado)
            titulos = {r["title"] for r in data}
            assert "Cazuela de vacuno" in titulos
            assert "Charquicán" in titulos
            for receta in data:
                assert "chilena" in receta["tags"]
                assert "guiso" in receta["tags"]

            # max_results acota la respuesta.
            resultado = await cliente.call_tool("search_recipes", {"max_results": 3})
            assert len(_data(resultado)) == 3

            # La búsqueda combina texto y tags.
            resultado = await cliente.call_tool(
                "search_recipes", {"query": "porotos", "tags": ["legumbres"]}
            )
            titulos = {r["title"] for r in _data(resultado)}
            assert "Porotos con riendas" in titulos

    asyncio.run(escenario())


def test_get_pantry_status_con_filtros(mcp_seeded: Any) -> None:
    async def escenario() -> None:
        async with Client(mcp) as cliente:
            resultado = await cliente.call_tool("get_pantry_status", {})
            data = _data(resultado)
            nombres = {item["product_name"] for item in data}
            assert nombres == {"arroz", "huevo", "aceite", "papa", "leche"}
            for item in data:
                assert item["location"] == "alacena"

            # Filtro por ubicación.
            resultado = await cliente.call_tool(
                "get_pantry_status", {"location": "refrigerador"}
            )
            assert _data(resultado) == []

            # Vencimientos: la leche vence en 7 días, el huevo en 21.
            resultado = await cliente.call_tool(
                "get_pantry_status", {"expiring_within_days": 7}
            )
            data = _data(resultado)
            assert [item["product_name"] for item in data] == ["leche"]

    asyncio.run(escenario())


def test_get_pantry_location_invalida_es_error_accionable(mcp_seeded: Any) -> None:
    async def escenario() -> None:
        async with Client(mcp) as cliente:
            with pytest.raises(ToolError):
                await cliente.call_tool("get_pantry_status", {"location": "bodega"})

    asyncio.run(escenario())


def test_resource_household_context(mcp_seeded: Any) -> None:
    async def escenario() -> None:
        async with Client(mcp) as cliente:
            contenido = await cliente.read_resource("household://1/context")
            data = getattr(contenido, "structured_content", None)
            if data is None:
                bloques = getattr(contenido, "content", contenido)
                primero = bloques[0] if isinstance(bloques, list) else bloques
                data = json.loads(primero.text)
            assert data["name"] == "Mi Hogar"
            assert data["currency"] == "CLP"

    asyncio.run(escenario())


def test_stdio_end_to_end(migrated_engine: Engine) -> None:
    """AC de la Task 5: el servidor responde por transporte stdio real.

    Levanta `python -m app.mcp_server` como subproceso (como lo haría Claude
    Desktop) y ejecuta las tres tools contra la BD migrada y sembrada.
    """
    with Session(migrated_engine) as session:
        seed(session)
    db_url = str(migrated_engine.url)

    transporte = StdioTransport(
        command=sys.executable,
        args=["-m", "app.mcp_server"],
        cwd=str(BACKEND_DIR),
        env={**os.environ, "DATABASE_URL": db_url},
    )

    async def escenario() -> None:
        async with Client(transporte) as cliente:
            hogar = _data(await cliente.call_tool("get_household_context", {}))
            assert hogar["name"] == "Mi Hogar"
            assert hogar["weekly_budget_clp"] == 45000

            recetas = _data(await cliente.call_tool("search_recipes", {"query": "cazuela"}))
            titulos = {r["title"] for r in recetas}
            # "Cazuela" aparece también en la descripción de la Carbonada.
            assert "Cazuela de vacuno" in titulos
            assert "Carbonada" in titulos

            despensa = _data(await cliente.call_tool("get_pantry_status", {}))
            assert {d["product_name"] for d in despensa} == {
                "arroz", "huevo", "aceite", "papa", "leche",
            }

    asyncio.run(escenario())
