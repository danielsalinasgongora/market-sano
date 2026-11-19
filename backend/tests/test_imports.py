# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests de importación de recetas desde URL con JSON-LD (Task 12).

Los HTML de `tests/fixtures/` son recetas reales con datos estructurados
schema.org/Recipe capturadas de sitios de cocina; se sirven con un fetcher
inyectado para que la suite no dependa de la red. La verificación manual del
cierre de tarea importa URLs reales contra el servicio en ejecución.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.main import create_app
from app.mcp import tools_read, tools_recipes  # noqa: F401 - registran las tools
from app.mcp.db import set_mcp_engine
from app.mcp.server import mcp
from app.models import Recipe, RecipeImportJob
from app.models.enums import ImportStatus
from app.seed import seed
from app.services import imports
from app.services.identidad import owner_implicito
from app.services.imports import ImportInvalido, importar_desde_url
from app.settings import Settings

FIXTURES = Path(__file__).parent / "fixtures"
URL_CHARQUICAN = "https://cocina-chilena.ejemplo/charquican"
URL_TORTILLA = "https://recetas.ejemplo/tortilla"


def _html(nombre: str) -> str:
    return (FIXTURES / nombre).read_text(encoding="utf-8")


def _fetcher_fixture():
    """Descarga simulada: cada URL conocida devuelve su HTML capturado."""
    paginas = {
        URL_CHARQUICAN: _html("receta_charquican.html"),
        URL_TORTILLA: _html("receta_tortilla.html"),
    }

    def fetch(url: str) -> str:
        return paginas[url]

    return fetch


def _fetcher_sin_json_ld():
    return lambda url: "<html><body><h1>Sin receta</h1></body></html>"


@pytest.fixture()
def engine_sembrado(migrated_engine: Engine) -> Engine:
    with Session(migrated_engine) as session:
        seed(session)
    return migrated_engine


@pytest.fixture()
def api(engine_sembrado: Engine) -> TestClient:
    return TestClient(create_app(Settings(database_url=str(engine_sembrado.url), _env_file=None)))


def _importar(
    engine: Engine, url: str, *, dry_run: bool = False, fetcher: Any = None
) -> dict[str, Any]:
    with Session(engine) as session:
        hogar, usuario = owner_implicito(session)
        return importar_desde_url(
            session, hogar.id, url, dry_run=dry_run,
            created_by=usuario.id, fetcher=fetcher or _fetcher_fixture(),
        )


def _jobs(engine: Engine) -> list[RecipeImportJob]:
    with Session(engine) as session:
        return list(session.exec(select(RecipeImportJob)).all())


def test_importa_dos_recetas_reales_con_json_ld(engine_sembrado: Engine) -> None:
    charquican = _importar(engine_sembrado, URL_CHARQUICAN)
    tortilla = _importar(engine_sembrado, URL_TORTILLA)

    # Receta 1: medidas caseras convertidas y plurales mapeados ("papas" → papa).
    assert charquican["dry_run"] is False
    assert charquican["title"] == "Charquicán de zapallo"
    assert charquican["base_servings"] == 4
    assert charquican["prep_minutes"] == 20 and charquican["cook_minutes"] == 40
    assert charquican["source_url"] == URL_CHARQUICAN
    assert "Pelar y cortar la papa" in charquican["instructions"]
    por_nombre = {i["product_name"]: i for i in charquican["ingredients"]}
    assert por_nombre["papa"]["quantity"] == 1000 and por_nombre["papa"]["unit"] == "g"
    assert por_nombre["aceite"]["quantity"] == 30       # 2 cucharadas → 30 ml
    assert por_nombre["sal"]["quantity"] == 5           # 1 cucharadita → 5 g
    assert por_nombre["cebolla"]["unit"] == "unidad"

    # Receta 2: porciones en lista y bloque HowToSection.
    assert tortilla["title"] == "Tortilla de papas y huevos"
    assert tortilla["base_servings"] == 6
    assert tortilla["cook_minutes"] == 25
    tortilla_por_nombre = {i["product_name"]: i for i in tortilla["ingredients"]}
    assert tortilla_por_nombre["huevo"]["quantity"] == 4
    assert tortilla_por_nombre["papa"]["quantity"] == 500
    assert tortilla_por_nombre["harina"]["quantity"] == 8

    with Session(engine_sembrado) as session:
        recetas = session.exec(select(Recipe).where(Recipe.source_url.is_not(None))).all()
        titulos = {r.title for r in recetas}
        assert {"Charquicán de zapallo", "Tortilla de papas y huevos"} <= titulos
        # Ambas quedan asociadas al hogar (draft propio, no receta comunitaria).
        assert all(r.household_id is not None for r in recetas)

    jobs = _jobs(engine_sembrado)
    assert len(jobs) == 2
    assert {j.status.value for j in jobs} == {"completed"}
    assert all(j.result_json and j.result_json["recipe_id"] for j in jobs)
    assert {j.source_value for j in jobs} == {URL_CHARQUICAN, URL_TORTILLA}
    assert all(j.completed_at is not None for j in jobs)


def test_ingredientes_no_resueltos_quedan_marcados(engine_sembrado: Engine) -> None:
    resultado = _importar(engine_sembrado, URL_TORTILLA)

    assert resultado["is_complete"] is False
    assert "warning" in resultado
    no_resueltos = {u["text"]: u for u in resultado["unresolved"]}
    assert set(no_resueltos) == {
        "2 dientes de ajo",
        "1 cucharada de merkén",
        "2 cucharadas de salsa de soya",
    }
    assert "diente" in no_resueltos["2 dientes de ajo"]["reason"]
    assert "equivalencia" in no_resueltos["1 cucharada de merkén"]["reason"]
    assert "no está en el catálogo" in no_resueltos["2 cucharadas de salsa de soya"]["reason"]
    # Los no resueltos no se inventan como ingredientes de la receta.
    creados = {i["product_name"] for i in resultado["ingredients"]}
    assert creados == {"huevo", "papa", "harina"}

    # El job conserva la lista completa para revisarla después.
    job = _jobs(engine_sembrado)[0]
    assert job.result_json is not None
    assert len(job.result_json["unresolved"]) == 3


def test_dry_run_no_persiste_receta_ni_job(engine_sembrado: Engine) -> None:
    vista = _importar(engine_sembrado, URL_CHARQUICAN, dry_run=True)

    assert vista["dry_run"] is True
    assert vista["job_id"] is None and vista["recipe_id"] is None
    assert vista["title"] == "Charquicán de zapallo"
    assert vista["ingredients"]  # la vista previa sí trae el mapeo
    with Session(engine_sembrado) as session:
        assert session.exec(
            select(Recipe).where(Recipe.source_url == URL_CHARQUICAN)
        ).first() is None
    assert _jobs(engine_sembrado) == []


def test_url_invalida_registra_job_fallido(engine_sembrado: Engine) -> None:
    with pytest.raises(ImportInvalido, match="URL inválida"):
        _importar(engine_sembrado, "no-es-una-url")

    jobs = _jobs(engine_sembrado)
    assert len(jobs) == 1
    assert jobs[0].status.value == "failed"
    assert jobs[0].source_type.value == "url"
    assert jobs[0].source_value == "no-es-una-url"
    assert "URL inválida" in (jobs[0].error_message or "")
    assert jobs[0].result_json is None and jobs[0].completed_at is not None


def test_pagina_sin_json_ld_registra_job_fallido(engine_sembrado: Engine) -> None:
    with pytest.raises(ImportInvalido, match="JSON-LD"):
        _importar(
            engine_sembrado, "https://sitio.ejemplo/sin-receta",
            fetcher=_fetcher_sin_json_ld(),
        )

    job = _jobs(engine_sembrado)[0]
    assert job.status.value == "failed"
    assert "JSON-LD" in (job.error_message or "")


def test_api_rest_importa_y_expone_la_vista_previa(
    api: TestClient, engine_sembrado: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(imports, "_descargar", lambda url: _fetcher_fixture()(url))

    previa = api.post("/api/v1/recipes/imports",
                      json={"url": URL_CHARQUICAN}, params={"dry_run": True})
    assert previa.status_code == 200, previa.text
    cuerpo = previa.json()
    assert cuerpo["dry_run"] is True and cuerpo["recipe_id"] is None

    creada = api.post("/api/v1/recipes/imports",
                      json={"url": URL_CHARQUICAN}, params={"dry_run": False})
    assert creada.status_code == 200, creada.text
    recipe_id = creada.json()["recipe_id"]
    assert recipe_id is not None

    detalle = api.get(f"/api/v1/recipes/{recipe_id}")
    assert detalle.status_code == 200
    assert detalle.json()["title"] == "Charquicán de zapallo"
    assert detalle.json()["source_url"] == URL_CHARQUICAN

    invalida = api.post("/api/v1/recipes/imports",
                        json={"url": "ftp://sin-receta"}, params={"dry_run": False})
    assert invalida.status_code == 422
    assert "URL inválida" in invalida.json()["detail"]
    with Session(engine_sembrado) as session:
        fallidos = session.exec(
            select(RecipeImportJob).where(RecipeImportJob.status == ImportStatus.failed)
        ).all()
    assert len(fallidos) == 1


def _texto(resultado: Any) -> Any:
    return json.loads(resultado.content[0].text)


def test_tool_mcp_import_recipe(
    engine_sembrado: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(imports, "_descargar", lambda url: _fetcher_fixture()(url))
    set_mcp_engine(engine_sembrado)

    async def escenario() -> None:
        async with Client(mcp) as cliente:
            nombres = {t.name for t in await cliente.list_tools()}
            assert "import_recipe" in nombres

            previa = _texto(await cliente.call_tool("import_recipe", {
                "url": URL_CHARQUICAN, "dry_run": True}))
            assert previa["dry_run"] is True and previa["recipe_id"] is None

            creada = _texto(await cliente.call_tool("import_recipe", {
                "url": URL_TORTILLA, "dry_run": False}))
            assert creada["recipe_id"] is not None
            assert creada["warning"]  # tortilla tiene ingredientes no resueltos

            with pytest.raises(ToolError, match="URL inválida"):
                await cliente.call_tool("import_recipe", {"url": "no-es-url"})

    try:
        asyncio.run(escenario())
    finally:
        set_mcp_engine(None)
