# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests del PriceService y sus endpoints (Task 7): trazabilidad, TTL y prioridad."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.main import create_app
from app.models import PriceSnapshot, ProductCatalog
from app.models.enums import PriceConfidence, PriceSource
from app.seed import seed
from app.services.prices import get_latest_price, registrar_snapshot
from app.settings import Settings


@pytest.fixture()
def client_precios(migrated_engine: Engine) -> TestClient:
    """API con BD migrada y sembrada (fixture por test: bases aisladas)."""
    with Session(migrated_engine) as session:
        seed(session)
    settings = Settings(database_url=str(migrated_engine.url), _env_file=None)
    app = create_app(settings)
    return TestClient(app)


@pytest.fixture()
def engine_sembrado(migrated_engine: Engine) -> Engine:
    """BD migrada y sembrada, para tests a nivel de servicio."""
    with Session(migrated_engine) as session:
        seed(session)
    return migrated_engine


def _id_producto(engine: Engine, nombre: str) -> int:
    with Session(engine) as session:
        producto = session.exec(
            select(ProductCatalog).where(ProductCatalog.canonical_name == nombre)
        ).one()
        return producto.id


def _snapshot(
    engine: Engine,
    product_id: int,
    *,
    source: PriceSource,
    price_clp: int,
    fetched_at: datetime,
) -> None:
    """Inserta un snapshot directo (simula lo que hará el conector en T9)."""
    with Session(engine) as session:
        session.add(
            PriceSnapshot(
                product_id=product_id,
                store_id="jumbo",
                price_clp=price_clp,
                unit_price_clp=price_clp,
                source=source,
                confidence=PriceConfidence.high,
                fetched_at=fetched_at,
            )
        )
        session.commit()


def test_post_precio_manual_y_get_con_metadatos(
    client_precios: TestClient, migrated_engine: Engine
) -> None:
    palta = _id_producto(migrated_engine, "palta")

    respuesta = client_precios.post(
        "/api/v1/prices",
        json={
            "product_id": palta,
            "store_id": "jumbo",
            "price_clp": 1600,
            "unit_price_clp": 1600,
        },
    )
    assert respuesta.status_code == 201
    data = respuesta.json()
    assert data["source"] == "manual"
    assert data["confidence"] == "high"
    assert data["unit_price_clp"] == 1600  # PPUM persistido (SERNAC)
    assert data["is_stale"] is False

    consulta = client_precios.get(f"/api/v1/products/{palta}/price", params={"store_id": "jumbo"})
    assert consulta.status_code == 200
    precio = consulta.json()["price"]
    assert precio is not None
    assert precio["price_clp"] == 1600
    assert precio["source_efectiva"] == "manual"
    assert precio["age_hours"] < 1


def test_producto_sin_precios_devuelve_null(
    client_precios: TestClient, migrated_engine: Engine
) -> None:
    arroz = _id_producto(migrated_engine, "arroz")
    respuesta = client_precios.get(
        f"/api/v1/products/{arroz}/price", params={"store_id": "unimarc"}
    )
    assert respuesta.status_code == 200
    assert respuesta.json() == {"product_id": arroz, "store_id": "unimarc", "price": None}


def test_producto_inexistente(client_precios: TestClient) -> None:
    assert (
        client_precios.get("/api/v1/products/9999/price", params={"store_id": "jumbo"}).status_code
        == 404
    )
    respuesta = client_precios.post(
        "/api/v1/prices",
        json={
            "product_id": 9999,
            "store_id": "jumbo",
            "price_clp": 100,
            "unit_price_clp": 100,
        },
    )
    assert respuesta.status_code == 404


def test_ppum_obligatorio_y_positivo(
    client_precios: TestClient, migrated_engine: Engine
) -> None:
    palta = _id_producto(migrated_engine, "palta")
    respuesta = client_precios.post(
        "/api/v1/prices",
        json={
            "product_id": palta,
            "store_id": "jumbo",
            "price_clp": 1600,
            "unit_price_clp": 0,  # PPUM inválido
        },
    )
    assert respuesta.status_code == 422


def test_el_snapshot_mas_reciente_gana(
    client_precios: TestClient, migrated_engine: Engine
) -> None:
    """Prioridad por frescura: el snapshot más reciente desplaza al anterior."""
    palta = _id_producto(migrated_engine, "palta")

    # 1) Un live de hace 2 horas.
    _snapshot(
        migrated_engine, palta, source=PriceSource.live, price_clp=1000,
        fetched_at=datetime.now(UTC) - timedelta(hours=2),
    )
    consulta = client_precios.get(f"/api/v1/products/{palta}/price", params={"store_id": "jumbo"})
    assert consulta.json()["price"]["price_clp"] == 1000

    # 2) Un manual de ahora lo desplaza (más reciente).
    client_precios.post(
        "/api/v1/prices",
        json={"product_id": palta, "store_id": "jumbo", "price_clp": 1600, "unit_price_clp": 1600},
    )
    consulta = client_precios.get(f"/api/v1/products/{palta}/price", params={"store_id": "jumbo"})
    assert consulta.json()["price"]["price_clp"] == 1600

    # 3) Un live nuevo lo desplaza de vuelta.
    _snapshot(migrated_engine, palta, source=PriceSource.live, price_clp=900,
              fetched_at=datetime.now(UTC))
    consulta = client_precios.get(f"/api/v1/products/{palta}/price", params={"store_id": "jumbo"})
    precio = consulta.json()["price"]
    assert precio["price_clp"] == 900
    assert precio["source"] == "live"


def test_ttl_marca_stale_y_recategoriza_a_cached(engine_sembrado: Engine) -> None:
    """Un live que supera el TTL se reporta stale con fuente efectiva cached."""
    palta = _id_producto(engine_sembrado, "palta")
    _snapshot(
        engine_sembrado, palta, source=PriceSource.live, price_clp=1000,
        fetched_at=datetime.now(UTC) - timedelta(hours=13),  # TTL por defecto: 12 h
    )
    with Session(engine_sembrado) as session:
        resuelto = get_latest_price(session, product_id=palta, store_id="jumbo")
        assert resuelto is not None
        assert resuelto.is_stale is True
        assert resuelto.source_efectiva == PriceSource.cached
        assert resuelto.age_hours >= 13


def test_manual_no_caduca_por_ttl(engine_sembrado: Engine) -> None:
    """El precio manual es palabra del usuario: nunca se marca stale."""
    palta = _id_producto(engine_sembrado, "palta")
    _snapshot(
        engine_sembrado, palta, source=PriceSource.manual, price_clp=1600,
        fetched_at=datetime.now(UTC) - timedelta(hours=200),
    )
    with Session(engine_sembrado) as session:
        resuelto = get_latest_price(session, product_id=palta, store_id="jumbo")
        assert resuelto is not None
        assert resuelto.is_stale is False
        assert resuelto.source_efectiva == PriceSource.manual
        assert resuelto.age_hours >= 200


def test_registrar_snapshot_valida_producto_y_precios(engine_sembrado: Engine) -> None:
    with Session(engine_sembrado) as session:
        with pytest.raises(ValueError):
            registrar_snapshot(
                session, product_id=999, store_id="jumbo", price_clp=100,
                unit_price_clp=100, source=PriceSource.manual,
                confidence=PriceConfidence.high,
            )
        palta = _id_producto(engine_sembrado, "palta")
        with pytest.raises(ValueError):
            registrar_snapshot(
                session, product_id=palta, store_id="jumbo", price_clp=0,
                unit_price_clp=100, source=PriceSource.manual,
                confidence=PriceConfidence.high,
            )
