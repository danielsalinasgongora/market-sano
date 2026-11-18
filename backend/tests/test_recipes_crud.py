# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests de recetas propias (Task 10): CRUD por API, create_recipe con dry_run
y rate_recipe por MCP."""

import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import Engine
from sqlmodel import Session, func, select

from app.main import create_app
from app.mcp import tools_recipes  # noqa: F401 - registra las tools
from app.mcp.db import set_mcp_engine
from app.mcp.server import mcp
from app.models import Recipe, RecipeRating
from app.seed import seed
from app.settings import Settings

RECETA = {
    "title": "Tortilla de papas",
    "description": "Clásica, para 4.",
    "base_servings": 4,
    "prep_minutes": 15,
    "cook_minutes": 25,
    "difficulty": "facil",
    "instructions": "## Preparación\nPelar, freír, cuajar.",
    "ingredients": [
        {"product": "papa", "quantity": 0.8, "unit": "kg"},
        {"product": "huevo", "quantity": 6, "unit": "unidad"},
        {"product": "Aceite", "quantity": 100, "unit": "ml"},
        {"product": "sal", "quantity": 5, "unit": "g", "optional": True},
    ],
    "steps": [
        {"instruction": "Pelar y cortar las papas en láminas.", "duration_minutes": 10},
        {"instruction": "Freír a fuego medio.", "duration_minutes": 15},
        {"instruction": "Batir los huevos, mezclar y cuajar."},
    ],
    "tags": ["Española", "vegetariana"],
}


@pytest.fixture()
def engine_sembrado(migrated_engine: Engine) -> Engine:
    with Session(migrated_engine) as session:
        seed(session)
    return migrated_engine


@pytest.fixture()
def api(engine_sembrado: Engine) -> TestClient:
    return TestClient(create_app(Settings(database_url=str(engine_sembrado.url), _env_file=None)))


def _recetas(engine: Engine) -> int:
    with Session(engine) as session:
        return session.exec(select(func.count()).select_from(Recipe)).one()


def test_crear_detalle_actualizar_y_borrar(api: TestClient, engine_sembrado: Engine) -> None:
    r = api.post("/api/v1/recipes", json=RECETA)
    assert r.status_code == 201, r.text
    recipe_id = r.json()["recipe_id"]

    detalle = api.get(f"/api/v1/recipes/{recipe_id}").json()
    papa = detalle["ingredients"][0]
    assert papa["product_name"] == "papa" and papa["quantity"] == 800 and papa["unit"] == "g"
    assert [s["step_number"] for s in detalle["steps"]] == [1, 2, 3]
    assert detalle["steps"][0]["duration_minutes"] == 10
    assert detalle["instructions"].startswith("## Preparación")
    assert detalle["tags"] == ["española", "vegetariana"]
    assert detalle["ingredients"][3]["optional"] is True

    editada = {**RECETA, "title": "Tortilla jugosa", "tags": ["rápida"],
               "steps": RECETA["steps"][:1]}
    r = api.put(f"/api/v1/recipes/{recipe_id}", json=editada)
    assert r.status_code == 200
    assert r.json()["title"] == "Tortilla jugosa" and r.json()["tags"] == ["rápida"]
    assert len(r.json()["steps"]) == 1

    assert any(x["recipe_id"] == recipe_id and x["own"]
               for x in api.get("/api/v1/recipes", params={"query": "jugosa"}).json())

    assert api.delete(f"/api/v1/recipes/{recipe_id}").status_code == 204
    assert api.get(f"/api/v1/recipes/{recipe_id}").status_code == 404


def test_dry_run_valida_sin_escribir(api: TestClient, engine_sembrado: Engine) -> None:
    antes = _recetas(engine_sembrado)
    r = api.post("/api/v1/recipes", params={"dry_run": "true"}, json=RECETA)
    assert r.status_code == 201
    assert r.json()["dry_run"] is True and r.json()["recipe_id"] is None
    assert _recetas(engine_sembrado) == antes


def test_ingrediente_fuera_del_catalogo_sugiere_parecidos(api: TestClient) -> None:
    receta = {**RECETA, "ingredients": [{"product": "papas", "quantity": 1, "unit": "kg"}]}
    r = api.post("/api/v1/recipes", json=receta)
    assert r.status_code == 422
    assert "papa" in r.json()["detail"] and "add_product_from_store" in r.json()["detail"]


def test_unidad_incompatible_y_alias(api: TestClient) -> None:
    r = api.post("/api/v1/recipes", json={
        **RECETA, "ingredients": [{"product": "leche", "quantity": 1, "unit": "kg"}]})
    assert r.status_code == 422 and "ml" in r.json()["detail"]
    r = api.post("/api/v1/recipes", params={"dry_run": "true"}, json={
        **RECETA, "ingredients": [{"product": "aguacate", "quantity": 2, "unit": "unidad"}]})
    assert r.json()["ingredients"][0]["product_name"] == "palta"  # alias resuelto


def test_recetas_de_la_semilla_son_de_solo_lectura(api: TestClient) -> None:
    cazuela = api.get("/api/v1/recipes", params={"query": "cazuela"}).json()[0]
    assert cazuela["own"] is False
    r = api.put(f"/api/v1/recipes/{cazuela['recipe_id']}", json=RECETA)
    assert r.status_code == 422 and "solo lectura" in r.json()["detail"]


def test_calificar_reemplaza_y_promedia(api: TestClient, engine_sembrado: Engine) -> None:
    cazuela = api.get("/api/v1/recipes", params={"query": "cazuela"}).json()[0]["recipe_id"]
    assert api.post(f"/api/v1/recipes/{cazuela}/ratings", json={"rating": 3}).json()[
        "rating_avg"] == 3
    r = api.post(f"/api/v1/recipes/{cazuela}/ratings", json={"rating": 5}).json()
    assert r["rating_avg"] == 5 and r["rating_count"] == 1  # mismo usuario: reemplaza
    assert api.post(f"/api/v1/recipes/{cazuela}/ratings", json={"rating": 6}).status_code == 422
    assert api.get(f"/api/v1/recipes/{cazuela}").json()["rating_avg"] == 5


def _texto(resultado: Any) -> Any:
    return json.loads(resultado.content[0].text)


def test_tools_mcp_create_recipe_y_rate_recipe(engine_sembrado: Engine) -> None:
    set_mcp_engine(engine_sembrado)
    antes = _recetas(engine_sembrado)
    mcp_args = {k: RECETA[k] for k in ("title", "ingredients", "steps", "tags", "difficulty")}

    async def escenario() -> int:
        async with Client(mcp) as c:
            assert {"create_recipe", "rate_recipe", "get_recipe"} <= {
                t.name for t in await c.list_tools()}
            vista = _texto(await c.call_tool("create_recipe", mcp_args))  # dry_run por defecto
            assert vista["dry_run"] is True and vista["recipe_id"] is None
            assert _recetas(engine_sembrado) == antes

            creada = _texto(await c.call_tool("create_recipe", {**mcp_args, "dry_run": False}))
            recipe_id = creada["recipe_id"]
            nota = _texto(await c.call_tool("rate_recipe", {"recipe_id": recipe_id, "rating": 4}))
            assert nota["rating_avg"] == 4
            detalle = _texto(await c.call_tool("get_recipe", {"recipe_id": recipe_id}))
            assert detalle["rating_count"] == 1 and len(detalle["steps"]) == 3

            with pytest.raises(ToolError, match="catálogo"):
                await c.call_tool("create_recipe", {
                    "title": "x", "ingredients": [{"product": "dragón", "quantity": 1,
                                                   "unit": "g"}]})
            return recipe_id

    try:
        recipe_id = asyncio.run(escenario())
    finally:
        set_mcp_engine(None)
    with Session(engine_sembrado) as session:
        assert session.exec(
            select(RecipeRating).where(RecipeRating.recipe_id == recipe_id)
        ).one().rating == 4
