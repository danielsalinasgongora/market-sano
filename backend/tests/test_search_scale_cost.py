# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests de búsqueda con filtros, escalado y costo por porción (Task 11).

Cubren las reglas del Anexo A (ceil en unidades discretas, 1 decimal en
peso/volumen), el costo calculado con PPUM y la trazabilidad de cada precio.
"""

import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.main import create_app
from app.mcp import tools_read, tools_recipes  # noqa: F401 - registran las tools
from app.mcp.db import set_mcp_engine
from app.mcp.server import mcp
from app.models import ProductCatalog
from app.seed import seed
from app.settings import Settings


@pytest.fixture()
def engine_sembrado(migrated_engine: Engine) -> Engine:
    with Session(migrated_engine) as session:
        seed(session)
    return migrated_engine


@pytest.fixture()
def api(engine_sembrado: Engine) -> TestClient:
    return TestClient(create_app(Settings(database_url=str(engine_sembrado.url), _env_file=None)))


def _crear(
    api: TestClient,
    titulo: str,
    ingredientes: list[dict[str, Any]],
    *,
    base_servings: int = 4,
    prep_minutes: int | None = None,
) -> int:
    r = api.post("/api/v1/recipes", json={
        "title": titulo,
        "base_servings": base_servings,
        "prep_minutes": prep_minutes,
        "ingredients": ingredientes,
        "tags": ["prueba"],
    })
    assert r.status_code == 201, r.text
    return r.json()["recipe_id"]


def _precio(
    api: TestClient,
    engine: Engine,
    producto: str,
    ppum: int,
    *,
    price: int | None = None,
    store_id: str = "jumbo",
) -> None:
    """Registra un precio manual del producto (PPUM: CLP/kg, CLP/L o CLP/unidad)."""
    with Session(engine) as session:
        product_id = session.exec(
            select(ProductCatalog).where(ProductCatalog.canonical_name == producto)
        ).one().id
    r = api.post("/api/v1/prices", json={
        "product_id": product_id,
        "store_id": store_id,
        "price_clp": price if price is not None else ppum,
        "unit_price_clp": ppum,
    })
    assert r.status_code == 201, r.text


def test_busqueda_filtra_por_costo_y_tiempo_y_ordena(
    api: TestClient, engine_sembrado: Engine
) -> None:
    _precio(api, engine_sembrado, "papa", 2000)   # CLP/kg
    _precio(api, engine_sembrado, "tomate", 300)  # CLP/unidad
    cara = _crear(api, "Guiso caro", [{"product": "papa", "quantity": 1, "unit": "kg"}],
                  prep_minutes=60)
    barata = _crear(api, "Ensalada barata", [{"product": "tomate", "quantity": 1,
                                              "unit": "unidad"}], prep_minutes=5)
    _crear(api, "Sin precios", [{"product": "ajo", "quantity": 3, "unit": "unidad"}],
           prep_minutes=5)

    todas = api.get("/api/v1/recipes", params={"tags": ["prueba"]}).json()
    costos = {x["title"]: x["cost_per_serving_clp"] for x in todas}
    assert costos == {"Guiso caro": 500, "Ensalada barata": 75, "Sin precios": None}
    assert {x["title"]: x["is_complete_cost"] for x in todas} == {
        "Guiso caro": True, "Ensalada barata": True, "Sin precios": False,
    }

    # El filtro de costo exige precios completos: "Sin precios" queda fuera.
    filtradas = api.get("/api/v1/recipes", params={
        "tags": ["prueba"], "max_cost_per_serving": 100}).json()
    assert [x["title"] for x in filtradas] == ["Ensalada barata"]

    rapidas = api.get("/api/v1/recipes", params={
        "tags": ["prueba"], "max_time_minutes": 10}).json()
    assert {x["title"] for x in rapidas} == {"Ensalada barata", "Sin precios"}

    por_costo = api.get("/api/v1/recipes", params={
        "tags": ["prueba"], "sort": "cost"}).json()
    assert [x["title"] for x in por_costo] == [
        "Ensalada barata", "Guiso caro", "Sin precios"]  # sin precio: al final

    api.post(f"/api/v1/recipes/{cara}/ratings", json={"rating": 5})
    api.post(f"/api/v1/recipes/{barata}/ratings", json={"rating": 2})
    por_rating = api.get("/api/v1/recipes", params={
        "tags": ["prueba"], "sort": "rating"}).json()
    assert [x["title"] for x in por_rating] == [
        "Guiso caro", "Ensalada barata", "Sin precios"]
    assert por_rating[0]["avg_rating"] == 5 and por_rating[0]["rating_count"] == 1

    assert api.get("/api/v1/recipes", params={"sort": "precio"}).status_code == 422
    assert api.get("/api/v1/recipes", params={"max_cost_per_serving": -1}).status_code == 422


def test_escalado_aplica_reglas_anexo_a(api: TestClient) -> None:
    tortilla = _crear(api, "Tortilla propia", [
        {"product": "papa", "quantity": 800, "unit": "g"},
        {"product": "huevo", "quantity": 3, "unit": "unidad"},
        {"product": "aceite", "quantity": 100, "unit": "ml"},
    ])
    datos = api.get(f"/api/v1/recipes/{tortilla}/scale",
                    params={"target_servings": 5}).json()
    assert datos["factor"] == 1.25 and datos["base_servings"] == 4
    cantidades = {x["product_name"]: x for x in datos["ingredients"]}
    assert cantidades["papa"]["quantity"] == 1000.0      # 1 decimal en peso
    assert cantidades["aceite"]["quantity"] == 125.0     # 1 decimal en volumen
    assert cantidades["huevo"]["quantity"] == 4          # 3.75 → ceil
    assert cantidades["huevo"]["original_quantity"] == 3

    # Receta de la semilla: Empanadas de pino (12 porciones, 3 huevos) → 5.
    empanadas = api.get("/api/v1/recipes", params={"query": "empanadas"}).json()[0]
    escalada = api.get(f"/api/v1/recipes/{empanadas['recipe_id']}/scale",
                       params={"target_servings": 5}).json()
    huevo = next(x for x in escalada["ingredients"] if x["product_name"] == "huevo")
    assert huevo["original_quantity"] == 3 and huevo["quantity"] == 2  # 1.25 → 2

    assert api.get(f"/api/v1/recipes/{tortilla}/scale",
                   params={"target_servings": 0}).status_code == 422
    assert api.get("/api/v1/recipes/9999/scale",
                   params={"target_servings": 4}).status_code == 404


def test_costo_por_porcion_con_trazabilidad(
    api: TestClient, engine_sembrado: Engine
) -> None:
    _precio(api, engine_sembrado, "papa", 2000, price=2000)    # CLP/kg
    _precio(api, engine_sembrado, "aceite", 5000, price=5000)  # CLP/L
    _precio(api, engine_sembrado, "huevo", 250, price=3000)    # docena: CLP/unidad
    receta = _crear(api, "Cena", [
        {"product": "papa", "quantity": 1000, "unit": "g"},
        {"product": "aceite", "quantity": 100, "unit": "ml"},
        {"product": "huevo", "quantity": 2, "unit": "unidad"},
    ])

    datos = api.get(f"/api/v1/recipes/{receta}/cost").json()
    assert datos["store_id"] == "jumbo"  # cadena por defecto del hogar sembrado
    assert datos["total_clp"] == 3000    # 2000 + 500 + 500
    assert datos["cost_per_serving_clp"] == 750
    assert datos["is_complete"] is True and "warning" not in datos

    lineas = {x["product_name"]: x for x in datos["ingredients"]}
    assert lineas["papa"]["cost_clp"] == 2000
    assert lineas["papa"]["ppum_unit"] == "CLP/kg"
    assert lineas["papa"]["price"]["source"] == "manual"
    assert lineas["papa"]["price"]["confidence"] == "high"
    assert lineas["papa"]["price"]["is_stale"] is False
    assert lineas["aceite"]["cost_clp"] == 500 and lineas["aceite"]["ppum_unit"] == "CLP/L"
    assert lineas["huevo"]["cost_clp"] == 500
    assert lineas["huevo"]["ppum_unit"] == "CLP/unidad"

    parcial = _crear(api, "Con ajo sin precio", [
        {"product": "papa", "quantity": 500, "unit": "g"},
        {"product": "ajo", "quantity": 1, "unit": "unidad"},
    ])
    p = api.get(f"/api/v1/recipes/{parcial}/cost").json()
    assert p["is_complete"] is False
    assert p["missing_products"] == ["ajo"]
    assert p["total_clp"] == 1000 and "ajo" in p["warning"]
    assert next(x for x in p["ingredients"] if x["product_name"] == "ajo")["price"] is None

    assert api.get("/api/v1/recipes/9999/cost").status_code == 404


def _texto(resultado: Any) -> Any:
    return json.loads(resultado.content[0].text)


def test_tools_mcp_busqueda_escalado_y_costo(api: TestClient, engine_sembrado: Engine) -> None:
    _precio(api, engine_sembrado, "papa", 2000, price=2000)
    _precio(api, engine_sembrado, "aceite", 5000, price=5000)
    _precio(api, engine_sembrado, "huevo", 250, price=3000)
    receta = _crear(api, "Cena MCP", [
        {"product": "papa", "quantity": 1000, "unit": "g"},
        {"product": "aceite", "quantity": 100, "unit": "ml"},
        {"product": "huevo", "quantity": 2, "unit": "unidad"},
    ])

    set_mcp_engine(engine_sembrado)

    async def escenario() -> None:
        async with Client(mcp) as cliente:
            nombres = {t.name for t in await cliente.list_tools()}
            assert {"search_recipes", "scale_recipe", "get_recipe_cost"} <= nombres

            busqueda = _texto(await cliente.call_tool("search_recipes", {
                "tags": ["prueba"], "max_cost_per_serving": 800, "sort": "cost"}))
            assert [x["title"] for x in busqueda] == ["Cena MCP"]

            escalada = _texto(await cliente.call_tool("scale_recipe", {
                "recipe_id": receta, "target_servings": 5}))
            huevo = next(x for x in escalada["ingredients"]
                         if x["product_name"] == "huevo")
            assert huevo["quantity"] == 3  # ceil de 2.5

            costo = _texto(await cliente.call_tool("get_recipe_cost", {
                "recipe_id": receta}))
            assert costo["total_clp"] == 3000 and costo["cost_per_serving_clp"] == 750
            assert costo["is_complete"] is True

    try:
        asyncio.run(escenario())
    finally:
        set_mcp_engine(None)
