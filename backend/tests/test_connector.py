# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests del conector de precios en vivo (Task 9) contra un conector MCP falso
que corre como subproceso stdio real (ver tests/conector_falso.py)."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.connectors.supermercados_cl import ppum_catalogo
from app.main import create_app
from app.models import PriceSnapshot, ProductCatalog, ProductStoreMatch
from app.models.enums import PriceConfidence, PriceSource
from app.seed import seed
from app.settings import Settings

FALSO = str(Path(__file__).with_name("conector_falso.py"))


@pytest.fixture()
def engine_sembrado(migrated_engine: Engine) -> Engine:
    with Session(migrated_engine) as session:
        seed(session)
    return migrated_engine


def _cliente(engine: Engine, modo: str = "ok", habilitado: bool = True) -> TestClient:
    settings = Settings(
        database_url=str(engine.url),
        supermercados_enabled=habilitado,
        supermercados_command=[sys.executable, FALSO, modo],
        _env_file=None,
    )
    return TestClient(create_app(settings))


def _producto(engine: Engine, nombre: str) -> int:
    with Session(engine) as session:
        return session.exec(
            select(ProductCatalog).where(ProductCatalog.canonical_name == nombre)
        ).one().id


def _snapshot(engine: Engine, product_id: int, source: PriceSource, horas: float) -> None:
    with Session(engine) as session:
        session.add(
            PriceSnapshot(
                product_id=product_id, store_id="jumbo", price_clp=1100, unit_price_clp=1100,
                source=source, confidence=PriceConfidence.high,
                fetched_at=datetime.now(UTC) - timedelta(hours=horas),
            )
        )
        session.commit()


def _precio(cliente: TestClient, product_id: int, store_id: str = "jumbo") -> dict:
    respuesta = cliente.get(f"/api/v1/products/{product_id}/price", params={"store_id": store_id})
    assert respuesta.status_code == 200
    return respuesta.json()


def test_ppum_se_convierte_a_la_unidad_del_catalogo() -> None:
    gramos = ProductCatalog(canonical_name="arroz", category="x", default_unit="g")
    unidad = ProductCatalog(
        canonical_name="tomate", category="x", default_unit="unidad", unit_weight_g=150
    )
    sin_peso = ProductCatalog(canonical_name="kiwi", category="x", default_unit="unidad")
    assert ppum_catalogo(gramos, 990, "kg") == 990
    assert ppum_catalogo(unidad, 1990, "kg") == 298  # 1990 CLP/kg × 0,150 kg
    assert ppum_catalogo(unidad, 600, "un") == 600
    assert ppum_catalogo(sin_peso, 1990, "kg") is None  # sin peso no se inventa
    assert ppum_catalogo(gramos, 1000, "lt") is None


def test_refresca_a_live_en_jumbo_con_ppum_convertido(engine_sembrado: Engine) -> None:
    tomate = _producto(engine_sembrado, "tomate")  # match sembrado del spike T8
    data = _precio(_cliente(engine_sembrado), tomate)
    assert "warning" not in data
    precio = data["price"]
    assert precio["source"] == "live" and precio["confidence_efectiva"] == "high"
    assert precio["price_clp"] == 995
    assert precio["unit_price_clp"] == 298  # por unidad (peso medio 150 g)
    assert precio["is_promotion"] is True  # listPrice > price


def test_unimarc_elige_el_resultado_por_sku_fijado(engine_sembrado: Engine) -> None:
    arroz = _producto(engine_sembrado, "arroz")
    with Session(engine_sembrado) as session:
        session.add(ProductStoreMatch(
            product_id=arroz, store_id="unimarc", store_url="https://x/arroz", sku="9411"
        ))
        session.commit()
    precio = _precio(_cliente(engine_sembrado), arroz, "unimarc")["price"]
    assert precio["price_clp"] == 890 and precio["source"] == "live"


def test_conector_caido_degrada_a_cache_con_confianza_baja(engine_sembrado: Engine) -> None:
    leche = _producto(engine_sembrado, "leche")
    _snapshot(engine_sembrado, leche, PriceSource.live, horas=20)  # live vencido
    data = _precio(_cliente(engine_sembrado, modo="error"), leche)
    assert "503" in data["warning"]
    assert data["price"]["price_clp"] == 1100
    assert data["price"]["source_efectiva"] == "cached"
    assert data["price"]["confidence_efectiva"] == "low"


def test_conector_inexistente_no_lanza_excepcion(engine_sembrado: Engine) -> None:
    leche = _producto(engine_sembrado, "leche")
    settings = Settings(
        database_url=str(engine_sembrado.url), supermercados_enabled=True,
        supermercados_command=["comando-que-no-existe-xyz"], _env_file=None,
    )
    data = _precio(TestClient(create_app(settings)), leche)
    assert data["price"] is None and "warning" in data


def test_manual_no_se_degrada_si_el_conector_falla(engine_sembrado: Engine) -> None:
    leche = _producto(engine_sembrado, "leche")
    _snapshot(engine_sembrado, leche, PriceSource.manual, horas=1)
    data = _precio(_cliente(engine_sembrado, modo="error"), leche)
    assert data["price"]["source"] == "manual"
    assert data["price"]["confidence_efectiva"] == "high"


def _match_antiguo(engine: Engine, product_id: int, horas: float) -> None:
    """Retrocede la fecha del match (la semilla lo crea 'ahora')."""
    with Session(engine) as session:
        match = session.exec(
            select(ProductStoreMatch).where(ProductStoreMatch.product_id == product_id)
        ).one()
        match.matched_at = datetime.now(UTC) - timedelta(hours=horas)
        session.add(match)
        session.commit()


def test_live_dentro_del_ttl_no_consulta_el_conector(engine_sembrado: Engine) -> None:
    leche = _producto(engine_sembrado, "leche")
    _match_antiguo(engine_sembrado, leche, horas=48)
    _snapshot(engine_sembrado, leche, PriceSource.live, horas=1)
    # Con el conector en modo error: si lo consultara, habría warning.
    data = _precio(_cliente(engine_sembrado, modo="error"), leche)
    assert "warning" not in data
    assert data["price"]["price_clp"] == 1100


def test_match_reemplazado_invalida_el_live_anterior(engine_sembrado: Engine) -> None:
    """Un live fresco del producto viejo no sirve si el match es más nuevo."""
    leche = _producto(engine_sembrado, "leche")
    _match_antiguo(engine_sembrado, leche, horas=-0.01)  # match recién (re)fijado
    _snapshot(engine_sembrado, leche, PriceSource.live, horas=1)
    precio = _precio(_cliente(engine_sembrado), leche)["price"]
    assert precio["price_clp"] == 1000  # refrescado desde el conector, no 1100


def test_live_vencido_se_refresca(engine_sembrado: Engine) -> None:
    leche = _producto(engine_sembrado, "leche")
    _snapshot(engine_sembrado, leche, PriceSource.live, horas=13)  # TTL 12 h
    precio = _precio(_cliente(engine_sembrado), leche)["price"]
    assert precio["price_clp"] == 1000 and precio["is_stale"] is False


def test_sin_match_o_deshabilitado_no_consulta(engine_sembrado: Engine) -> None:
    kiwi = _producto(engine_sembrado, "kiwi")  # sin match sembrado
    assert _precio(_cliente(engine_sembrado, modo="error"), kiwi) == {
        "product_id": kiwi, "store_id": "jumbo", "price": None
    }
    leche = _producto(engine_sembrado, "leche")
    data = _precio(_cliente(engine_sembrado, modo="error", habilitado=False), leche)
    assert data["price"] is None and "warning" not in data


def test_semilla_crea_los_20_matches_de_jumbo_sin_duplicar(engine_sembrado: Engine) -> None:
    with Session(engine_sembrado) as session:
        seed(session)  # segunda corrida
        matches = session.exec(select(ProductStoreMatch)).all()
        assert len(matches) == 20
        assert {m.store_id for m in matches} == {"jumbo"}
