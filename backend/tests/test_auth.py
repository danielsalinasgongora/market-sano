# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests de autenticación local y del modo sin login (Task 13)."""

import hashlib
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.main import create_app
from app.models import ApiToken, User
from app.seed import seed
from app.services.auth import PRIVACY_NOTICE_VERSION
from app.settings import Settings

EMAIL = "ana@example.cl"
PASSWORD = "clave-segura-123"


@pytest.fixture()
def engine_sembrado(migrated_engine: Engine) -> Engine:
    with Session(migrated_engine) as session:
        seed(session)
    return migrated_engine


def _app(engine: Engine, mode: str) -> TestClient:
    return TestClient(
        create_app(
            Settings(database_url=str(engine.url), auth_mode=mode, _env_file=None)
        )
    )


@pytest.fixture()
def api_none(engine_sembrado: Engine) -> TestClient:
    return _app(engine_sembrado, "none")


@pytest.fixture()
def api_local(engine_sembrado: Engine) -> TestClient:
    return _app(engine_sembrado, "local")


def _registro(**extra: Any) -> dict[str, Any]:
    datos = {
        "email": EMAIL,
        "password": PASSWORD,
        "display_name": "Ana",
        "privacy_consent": True,
        "privacy_notice_version": PRIVACY_NOTICE_VERSION,
    }
    datos.update(extra)
    return datos


def _registrar(api: TestClient, **extra: Any) -> dict[str, Any]:
    r = api.post("/api/v1/auth/register", json=_registro(**extra))
    assert r.status_code == 201, r.text
    return r.json()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_auth_mode_none_opera_como_owner_sin_login(
    api_none: TestClient, engine_sembrado: Engine
) -> None:
    me = api_none.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["auth_mode"] == "none"
    assert me.json()["user"]["email"] == "owner@marketsano.local"
    assert me.json()["user"]["role"] == "owner"
    assert me.json()["user"]["household_id"] is not None

    # Lectura y escritura funcionan sin credenciales.
    assert api_none.get("/api/v1/recipes").status_code == 200
    creada = api_none.post("/api/v1/recipes", json={
        "title": "Receta sin login",
        "ingredients": [{"product": "papa", "quantity": 1, "unit": "kg"}],
    })
    assert creada.status_code == 201, creada.text
    assert api_none.get(f"/api/v1/recipes/{creada.json()['recipe_id']}").status_code == 200


def test_registro_exige_consentimiento_afirmativo(
    api_local: TestClient, engine_sembrado: Engine
) -> None:
    sin_consentimiento = _registro()
    sin_consentimiento.pop("privacy_consent")
    for payload in (_registro(privacy_consent=False), sin_consentimiento):
        r = api_local.post("/api/v1/auth/register", json=payload)
        assert r.status_code == 422, r.text
        assert "aviso de privacidad" in r.json()["detail"].lower()

    # La versión aceptada debe ser la vigente (el aviso pudo cambiar).
    r = api_local.post(
        "/api/v1/auth/register",
        json=_registro(privacy_notice_version="2020-01-01"),
    )
    assert r.status_code == 422

    with Session(engine_sembrado) as session:
        assert session.exec(select(User).where(User.email == EMAIL)).first() is None


def test_registro_login_me_y_password_argon2id(
    api_local: TestClient, engine_sembrado: Engine
) -> None:
    registro = _registrar(api_local)
    token = registro["token"]
    assert registro["token_type"] == "bearer"
    assert registro["user"]["email"] == EMAIL
    assert registro["user"]["role"] == "owner"
    assert registro["user"]["household_id"] is not None
    assert registro["user"]["privacy_consent_version"] == PRIVACY_NOTICE_VERSION

    with Session(engine_sembrado) as session:
        usuario = session.exec(select(User).where(User.email == EMAIL)).one()
        assert usuario.password_hash is not None
        assert usuario.password_hash.startswith("$argon2id$")
        assert PASSWORD not in usuario.password_hash
        assert usuario.privacy_consent_at is not None
        fila = session.exec(select(ApiToken).where(ApiToken.user_id == usuario.id)).one()
        assert fila.token_hash != token
        assert fila.token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert fila.scopes == ["read", "write_draft"]
        assert fila.last_used_at is None

    # /me identifica al usuario autenticado.
    me = api_local.get("/api/v1/auth/me", headers=_bearer(token))
    assert me.status_code == 200
    assert me.json()["auth_mode"] == "local"
    assert me.json()["user"]["email"] == EMAIL
    assert me.json()["user"]["display_name"] == "Ana"

    # El token se usa y se registra la última utilización.
    with Session(engine_sembrado) as session:
        assert session.exec(select(ApiToken)).first().last_used_at is not None

    # Login correcto emite otro Bearer; la contraseña incorrecta no filtra cuentas.
    malo = api_local.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": "no-es-la-clave"}
    )
    assert malo.status_code == 401
    assert malo.json()["detail"] == "Email o contraseña incorrectos."
    inexistente = api_local.post(
        "/api/v1/auth/login", json={"email": "nadie@example.cl", "password": PASSWORD}
    )
    assert inexistente.status_code == 401
    assert inexistente.json()["detail"] == malo.json()["detail"]

    login = api_local.post(
        "/api/v1/auth/login", json={"email": EMAIL.upper(), "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    token2 = login.json()["token"]
    assert token2 and token2 != token
    assert api_local.get("/api/v1/auth/me", headers=_bearer(token2)).status_code == 200


def test_sin_token_en_modo_local_es_401(api_local: TestClient) -> None:
    _registrar(api_local)

    sin = api_local.get("/api/v1/recipes")
    assert sin.status_code == 401
    assert sin.headers["www-authenticate"] == "Bearer"
    assert "Bearer" in sin.json()["detail"]
    assert api_local.get("/api/v1/auth/me").status_code == 401

    assert api_local.get(
        "/api/v1/recipes", headers={"Authorization": "Basic abc"}
    ).status_code == 401
    assert api_local.get(
        "/api/v1/recipes", headers=_bearer("token-inventado")
    ).status_code == 401


def test_token_valido_abre_la_api_de_datos(api_local: TestClient) -> None:
    token = _registrar(api_local)["token"]

    assert api_local.get("/api/v1/recipes", headers=_bearer(token)).status_code == 200
    assert api_local.get(
        "/api/v1/recipes/1", headers=_bearer(token)
    ).status_code == 200  # receta de la semilla

    # Los endpoints públicos siguen abiertos para healthcheck y login.
    assert api_local.get("/health").status_code == 200
    assert api_local.get("/api/v1/auth/privacy").status_code == 200


def test_registro_valida_email_duplicado_y_password_corta(
    api_local: TestClient,
) -> None:
    _registrar(api_local)

    duplicado = api_local.post("/api/v1/auth/register", json=_registro())
    assert duplicado.status_code == 409
    assert "Ya existe" in duplicado.json()["detail"]

    otra = api_local.post(
        "/api/v1/auth/register",
        json=_registro(email="otra@example.cl", password="corta"),
    )
    assert otra.status_code == 422

    invalido = api_local.post(
        "/api/v1/auth/register", json=_registro(email="sin-arroba")
    )
    assert invalido.status_code == 422
    assert "Email inválido" in invalido.json()["detail"]
