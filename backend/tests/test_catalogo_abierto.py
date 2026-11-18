# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests del catálogo abierto (Task 9b): búsqueda en cadena, alta con dry_run
y entrada al ciclo de refresco live (T9), con el conector MCP falso por stdio."""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client
from sqlalchemy import Engine
from sqlmodel import Session, func, select

from app.main import create_app
from app.mcp import tools_catalog  # noqa: F401 - registra las tools
from app.mcp.db import set_mcp_engine
from app.mcp.server import mcp
from app.models import ProductCatalog, ProductStoreMatch
from app.seed import seed
from app.services.catalogo_abierto import inferir_pack
from app.settings import Settings

FALSO = str(Path(__file__).with_name("conector_falso.py"))
ARROZ_MERKAT = {
    "store_id": "unimarc",
    "store_url": "https://www.unimarc.cl/product/arroz-merkat-g2-1kg",
    "sku": "9411",
    "store_product_name": "Arroz Merkat G2 1 Kg",
    "unit": "kg",
}


@pytest.fixture()
def engine_sembrado(migrated_engine: Engine) -> Engine:
    with Session(migrated_engine) as session:
        seed(session)
    return migrated_engine


def _cliente(engine: Engine, habilitado: bool = True) -> TestClient:
    settings = Settings(
        database_url=str(engine.url), supermercados_enabled=habilitado,
        supermercados_command=[sys.executable, FALSO, "ok"], _env_file=None,
    )
    return TestClient(create_app(settings))


def _contar(engine: Engine, modelo: Any) -> int:
    with Session(engine) as session:
        return session.exec(select(func.count()).select_from(modelo)).one()


def test_inferir_pack_desde_el_nombre() -> None:
    assert inferir_pack("Arroz Merkat G2 1 Kg", "g") == ("1 Kg", 1000.0)
    assert inferir_pack("Leche Entera 1 L", "ml") == ("1 L", 1000.0)
    assert inferir_pack("Aceite Vegetal 900 ml", "ml") == ("900 ml", 900.0)
    assert inferir_pack("Huevos Extra Grandes 20 un.", "unidad") == ("20 un", 20.0)
    assert inferir_pack("Pollo Entero Fresco", "g") == (None, None)
    assert inferir_pack("Palta Hass 1 kg", "unidad") == (None, None)  # incoherente


def test_busqueda_en_cadena_no_escribe(engine_sembrado: Engine) -> None:
    antes = _contar(engine_sembrado, ProductCatalog)
    r = _cliente(engine_sembrado).get(
        "/api/v1/stores/unimarc/products", params={"query": "arroz"}
    )
    assert r.status_code == 200
    productos = r.json()["products"]
    assert {p["sku"] for p in productos} == {"111", "9411"}
    assert all({"price", "unitPrice", "unit", "url"} <= p.keys() for p in productos)
    assert _contar(engine_sembrado, ProductCatalog) == antes


def test_busqueda_con_conector_deshabilitado_es_503(engine_sembrado: Engine) -> None:
    r = _cliente(engine_sembrado, habilitado=False).get(
        "/api/v1/stores/jumbo/products", params={"query": "arroz"}
    )
    assert r.status_code == 503
    assert "SUPERMERCADOS_ENABLED" in r.json()["detail"]


def test_alta_dry_run_por_defecto_no_escribe(engine_sembrado: Engine) -> None:
    productos, matches = _contar(engine_sembrado, ProductCatalog), _contar(
        engine_sembrado, ProductStoreMatch
    )
    r = _cliente(engine_sembrado).post(
        "/api/v1/products/from-store", json={**ARROZ_MERKAT, "canonical_name": "arroz merkat"}
    )
    assert r.status_code == 200
    vista = r.json()
    assert vista["dry_run"] is True and vista["accion"] == "crear"
    assert vista["producto"]["default_unit"] == "g"
    assert vista["producto"]["purchase_size"] == 1000.0
    assert _contar(engine_sembrado, ProductCatalog) == productos
    assert _contar(engine_sembrado, ProductStoreMatch) == matches


def test_alta_crea_producto_y_entra_al_refresco_live(engine_sembrado: Engine) -> None:
    cliente = _cliente(engine_sembrado)
    r = cliente.post(
        "/api/v1/products/from-store",
        params={"dry_run": "false"},
        json={**ARROZ_MERKAT, "canonical_name": "Arroz Merkat", "category": "despensa"},
    )
    assert r.status_code == 200
    product_id = r.json()["producto"]["product_id"]
    with Session(engine_sembrado) as session:
        producto = session.get(ProductCatalog, product_id)
        assert producto.canonical_name == "arroz merkat" and producto.default_unit == "g"

    precio = cliente.get(
        f"/api/v1/products/{product_id}/price", params={"store_id": "unimarc"}
    ).json()["price"]
    assert precio["source"] == "live" and precio["price_clp"] == 890  # elegido por SKU


def test_alta_vincula_producto_existente_por_nombre(engine_sembrado: Engine) -> None:
    r = _cliente(engine_sembrado).post(
        "/api/v1/products/from-store",
        params={"dry_run": "false"},
        json={**ARROZ_MERKAT, "canonical_name": "Arroz"},
    )
    vista = r.json()
    assert vista["accion"] == "vincular" and vista["match"] == "crear"
    # Repetir reemplaza el match, no lo duplica.
    r = _cliente(engine_sembrado).post(
        "/api/v1/products/from-store",
        params={"dry_run": "false"},
        json={**ARROZ_MERKAT, "canonical_name": "arroz"},
    )
    assert r.json()["match"] == "reemplazar"
    with Session(engine_sembrado) as session:
        arroz = session.exec(
            select(ProductCatalog).where(ProductCatalog.canonical_name == "arroz")
        ).one()
        tiendas = session.exec(
            select(ProductStoreMatch.store_id).where(ProductStoreMatch.product_id == arroz.id)
        ).all()
        assert sorted(tiendas) == ["jumbo", "unimarc"]


def test_alta_rechaza_unidad_incompatible(engine_sembrado: Engine) -> None:
    r = _cliente(engine_sembrado).post(
        "/api/v1/products/from-store",
        json={**ARROZ_MERKAT, "canonical_name": "leche"},  # leche se mide en ml
    )
    assert r.status_code == 422
    assert "PPUM" in r.json()["detail"]


def test_tools_mcp_del_catalogo_abierto(
    engine_sembrado: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUPERMERCADOS_ENABLED", "true")
    monkeypatch.setenv("SUPERMERCADOS_COMMAND", json.dumps([sys.executable, FALSO, "ok"]))
    set_mcp_engine(engine_sembrado)
    antes = _contar(engine_sembrado, ProductCatalog)

    async def escenario() -> None:
        async with Client(mcp) as cliente:
            nombres = {t.name for t in await cliente.list_tools()}
            assert {"search_store_products", "add_product_from_store"} <= nombres

            r = await cliente.call_tool(
                "search_store_products", {"query": "arroz", "store_id": "unimarc"}
            )
            assert {p["sku"] for p in json.loads(r.content[0].text)} == {"111", "9411"}

            r = await cliente.call_tool(
                "add_product_from_store", {**ARROZ_MERKAT, "canonical_name": "arroz merkat"}
            )
            assert json.loads(r.content[0].text)["dry_run"] is True

    try:
        asyncio.run(escenario())
    finally:
        set_mcp_engine(None)
    assert _contar(engine_sembrado, ProductCatalog) == antes  # dry_run no escribió
