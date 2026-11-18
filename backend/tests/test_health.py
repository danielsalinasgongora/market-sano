# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests del healthcheck y de la raíz de la API."""

from fastapi.testclient import TestClient


def test_health_ok(client: TestClient) -> None:
    """GET /health debe devolver 200 con el contrato de la spec §3.11."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "connected"}


def test_raiz_presenta_la_api(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["app"] == "Market Sano API"
    assert data["docs"] == "/docs"


def test_openapi_disponible(client: TestClient) -> None:
    """OpenAPI/Swagger es requisito para la integración con Home Assistant (§4.1)."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    info = response.json()["info"]
    assert info["title"] == "Market Sano API"
    assert info["license"]["name"] == "GPL-3.0-or-later"
