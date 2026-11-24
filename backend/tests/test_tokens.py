# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests de tokens de API, scopes y permisos MCP por rol (Task 15)."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.main import create_app
from app.mcp.db import set_mcp_engine
from app.mcp.permissions import (
    ROLE_SCOPES,
    contexto_mcp,
    exigir_confirmacion,
    exigir_escritura,
)
from app.mcp_server import mcp
from app.models import ApiToken, Household, HouseholdMember, User
from app.models.enums import Role
from app.seed import seed
from app.services.auth import emitir_token, hash_password, hash_token
from app.services.tokens import TokenSinPermiso, crear_token
from app.settings import Settings

BACKEND_DIR = Path(__file__).resolve().parent.parent
PASSWORD = "clave-segura-123"


@pytest.fixture()
def engine_sembrado(migrated_engine: Engine) -> Engine:
    with Session(migrated_engine) as session:
        seed(session)
    return migrated_engine


@pytest.fixture()
def api_local(engine_sembrado: Engine) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                database_url=str(engine_sembrado.url), auth_mode="local", _env_file=None
            )
        )
    )


def _usuario(
    engine: Engine, email: str, rol: Role, household_id: int
) -> tuple[User, str]:
    with Session(engine) as session:
        usuario = User(
            email=email,
            display_name=email.split("@")[0],
            password_hash=hash_password(PASSWORD),
        )
        session.add(usuario)
        session.flush()
        session.add(
            HouseholdMember(household_id=household_id, user_id=usuario.id, role=rol)
        )
        session.commit()
        session.refresh(usuario)
        session.expunge(usuario)
        return usuario, emitir_token(session, usuario)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _hogar_defecto(engine: Engine) -> int:
    with Session(engine) as session:
        hogar = session.exec(select(Household).order_by(Household.id)).first()
        assert hogar is not None
        return hogar.id


def test_endpoint_tokens_muestra_valor_una_vez_y_revoca(
    api_local: TestClient, engine_sembrado: Engine
) -> None:
    r = api_local.post(
        "/api/v1/auth/register",
        json={
            "email": "ana@example.cl",
            "password": PASSWORD,
            "display_name": "Ana",
            "privacy_consent": True,
        },
    )
    assert r.status_code == 201, r.text
    login_token = r.json()["token"]

    creado = api_local.post(
        "/api/v1/tokens",
        headers=_bearer(login_token),
        json={"name": "home-assistant", "scopes": ["read", "confirm"]},
    )
    assert creado.status_code == 201, creado.text
    datos = creado.json()
    assert datos["scopes"] == ["read", "confirm"]
    assert datos["token"] and datos["token"] != login_token
    assert datos["warning"]

    with Session(engine_sembrado) as session:
        fila = session.exec(
            select(ApiToken).where(ApiToken.token_hash == hash_token(datos["token"]))
        ).one()
        assert fila.scopes == ["read", "confirm"]
        assert fila.name == "home-assistant"

    assert api_local.get(
        "/api/v1/recipes", headers=_bearer(datos["token"])
    ).status_code == 200

    listado = api_local.get("/api/v1/tokens", headers=_bearer(login_token))
    assert listado.status_code == 200
    propios = [t for t in listado.json() if t["id"] == datos["id"]]
    assert propios and propios[0]["name"] == "home-assistant"
    assert all("token" not in t and "token_hash" not in t for t in listado.json())

    assert api_local.delete(
        f"/api/v1/tokens/{datos['id']}", headers=_bearer(login_token)
    ).status_code == 204
    assert api_local.get(
        "/api/v1/recipes", headers=_bearer(datos["token"])
    ).status_code == 401

    ajeno = api_local.delete(
        "/api/v1/tokens/999999", headers=_bearer(login_token)
    )
    assert ajeno.status_code == 422


def test_scopes_limitados_por_rol(engine_sembrado: Engine) -> None:
    hogar = _hogar_defecto(engine_sembrado)
    viewer, _ = _usuario(engine_sembrado, "viewer@example.cl", Role.viewer, hogar)
    member, _ = _usuario(engine_sembrado, "member@example.cl", Role.member, hogar)
    owner, _ = _usuario(engine_sembrado, "owner2@example.cl", Role.owner, hogar)

    with Session(engine_sembrado) as session:
        assert ROLE_SCOPES[Role.viewer] == {"read"}
        assert ROLE_SCOPES[Role.member] == {"read", "write_draft"}

        with pytest.raises(TokenSinPermiso, match="write_draft"):
            crear_token(session, viewer, name="v", scopes=["read", "write_draft"])
        with pytest.raises(TokenSinPermiso, match="confirm"):
            crear_token(session, member, name="m", scopes=["read", "confirm"])
        assert crear_token(
            session, member, name="m", scopes=["read", "write_draft"]
        )["scopes"] == ["read", "write_draft"]
        assert crear_token(
            session, owner, name="o", scopes=["read", "confirm"]
        )["scopes"] == ["read", "confirm"]
        with pytest.raises(ValueError, match="desconocidos"):
            crear_token(session, owner, name="x", scopes=["root"])


def test_cli_create_token_autentica(
    api_local: TestClient, engine_sembrado: Engine
) -> None:
    with Session(engine_sembrado) as session:
        session.add(
            User(
                email="cli@example.cl",
                display_name="CLI",
                password_hash=hash_password(PASSWORD),
            )
        )
        session.commit()
        usuario = session.exec(select(User).where(User.email == "cli@example.cl")).one()
        hogar = session.exec(select(Household).order_by(Household.id)).first()
        session.add(
            HouseholdMember(household_id=hogar.id, user_id=usuario.id, role=Role.owner)
        )
        session.commit()

    db_path = Path(engine_sembrado.url.database or "").as_posix()
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{db_path}",
        "AUTH_MODE": "none",
    }
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.create_token",
            "--email",
            "cli@example.cl",
            "--name",
            "cli-test",
            "--scopes",
            "read,write_draft",
        ],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    lineas = [x.strip() for x in proc.stdout.splitlines() if x.strip()]
    token = lineas[1]
    assert token and " " not in token

    assert api_local.get("/api/v1/recipes", headers=_bearer(token)).status_code == 200
    with Session(engine_sembrado) as session:
        fila = session.exec(
            select(ApiToken).where(ApiToken.token_hash == hash_token(token))
        ).one()
        assert fila.scopes == ["read", "write_draft"]


def test_permisos_mcp_por_rol_y_scope(
    engine_sembrado: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    hogar = _hogar_defecto(engine_sembrado)
    viewer, _ = _usuario(engine_sembrado, "viewer@example.cl", Role.viewer, hogar)
    member, _ = _usuario(engine_sembrado, "member@example.cl", Role.member, hogar)
    owner, _ = _usuario(engine_sembrado, "owner2@example.cl", Role.owner, hogar)

    with Session(engine_sembrado) as session:
        tok_viewer = crear_token(session, viewer, name="v", scopes=["read"])["token"]
        tok_member = crear_token(
            session, member, name="m", scopes=["read", "write_draft"]
        )["token"]
        tok_confirm = crear_token(
            session, owner, name="o", scopes=["read", "confirm"]
        )["token"]

        monkeypatch.setenv("MCP_API_TOKEN", tok_viewer)
        ctx = contexto_mcp(session)
        assert ctx.rol is Role.viewer and ctx.scopes == {"read"}
        with pytest.raises(ToolError, match="write_draft"):
            exigir_escritura(ctx)
        with pytest.raises(ToolError, match="confirm"):
            exigir_confirmacion(ctx)

        monkeypatch.setenv("MCP_API_TOKEN", tok_member)
        ctx = contexto_mcp(session)
        assert ctx.rol is Role.member
        assert ctx.scopes == {"read", "write_draft"}
        exigir_escritura(ctx)
        with pytest.raises(ToolError, match="confirm"):
            exigir_confirmacion(ctx)

        monkeypatch.setenv("MCP_API_TOKEN", tok_confirm)
        ctx = contexto_mcp(session)
        assert ctx.scopes == {"read", "confirm"}
        exigir_confirmacion(ctx)
        with pytest.raises(ToolError, match="write_draft"):
            exigir_escritura(ctx)

    set_mcp_engine(engine_sembrado)
    monkeypatch.setenv("MCP_API_TOKEN", tok_viewer)

    async def escenario() -> None:
        async with Client(mcp) as cliente:
            lectura = await cliente.call_tool("search_recipes", {"query": "cazuela"})
            assert lectura.content
            with pytest.raises(ToolError, match="write_draft"):
                await cliente.call_tool(
                    "create_recipe",
                    {
                        "title": "No permitida",
                        "ingredients": [
                            {"product": "papa", "quantity": 1, "unit": "kg"}
                        ],
                    },
                )

    try:
        asyncio.run(escenario())
    finally:
        set_mcp_engine(None)

    # Un token member sí escribe en draft.
    set_mcp_engine(engine_sembrado)
    monkeypatch.setenv("MCP_API_TOKEN", tok_member)

    async def escritura() -> dict[str, Any]:
        async with Client(mcp) as cliente:
            resultado = await cliente.call_tool(
                "create_recipe",
                {
                    "title": "Borrador member",
                    "ingredients": [{"product": "papa", "quantity": 1, "unit": "kg"}],
                },
            )
            return json.loads(resultado.content[0].text)

    try:
        borrador = asyncio.run(escritura())
    finally:
        set_mcp_engine(None)
        monkeypatch.delenv("MCP_API_TOKEN", raising=False)

    assert borrador["dry_run"] is True
    assert borrador["title"] == "Borrador member"

    monkeypatch.setenv("MCP_API_TOKEN", "token-inventado")
    with Session(engine_sembrado) as session, pytest.raises(ToolError, match="inválido"):
        contexto_mcp(session)
