# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests del planificador semanal (Task 16): draft, entradas, estimación por
cadena con snapshots y estado del presupuesto."""

import asyncio
import json
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.main import create_app
from app.mcp.db import set_mcp_engine
from app.mcp_server import mcp
from app.models import (
    BudgetSnapshot,
    Household,
    HouseholdMember,
    MealPlan,
    ProductCatalog,
    Recipe,
    User,
)
from app.models.enums import Role
from app.seed import seed
from app.services.auth import emitir_token, hash_password
from app.services.identidad import owner_implicito
from app.services.planner import (
    PlanInvalido,
    PresupuestoInsuficiente,
    confirmar_plan,
    crear_plan,
    definir_entrada,
    estado_presupuesto,
    estimar_costo_plan,
    intercambiar_comida,
    obtener_plan,
    sugerir_plan,
)
from app.services.prices import registrar_precio_manual
from app.services.recipes import costo_receta
from app.services.tokens import crear_token
from app.settings import Settings

PASSWORD = "clave-segura-123"
LUNES = date(2026, 11, 23)
PPUM_POR_UNIDAD = {"g": 5_000, "ml": 3_000, "unidad": 1_200}


@pytest.fixture()
def engine_sembrado(migrated_engine: Engine) -> Engine:
    """Semilla + precios manuales en jumbo y santaisabel (la semilla no trae)."""
    with Session(migrated_engine) as session:
        seed(session)
        for producto in session.exec(select(ProductCatalog)).all():
            ppum = PPUM_POR_UNIDAD[producto.default_unit]
            for cadena in ("jumbo", "santaisabel"):
                registrar_precio_manual(
                    session,
                    product_id=producto.id,
                    store_id=cadena,
                    price_clp=ppum,
                    unit_price_clp=ppum,
                )
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


def _hogar(engine: Engine) -> int:
    with Session(engine) as session:
        hogar = session.exec(select(Household).order_by(Household.id)).first()
        assert hogar is not None
        return hogar.id


def _recetas_completas(engine: Engine, cantidad: int = 2) -> list[tuple[int, int]]:
    """(recipe_id, costo base) de recetas con precio completo en jumbo."""
    with Session(engine) as session:
        elegidas: list[tuple[int, int]] = []
        for receta in session.exec(select(Recipe).order_by(Recipe.id)).all():
            detalle = costo_receta(session, receta.id, "jumbo")
            if detalle["is_complete"] and detalle["total_clp"] > 0:
                elegidas.append((receta.id, detalle["total_clp"]))
            if len(elegidas) == cantidad:
                return elegidas
    pytest.fail(f"La semilla no tiene {cantidad} recetas con precio completo en jumbo")


def _usuario(engine: Engine, email: str, rol: Role, household_id: int) -> str:
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
        return emitir_token(session, usuario)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _json(resultado: Any) -> Any:
    return json.loads(resultado.content[0].text)


def test_plan_unico_por_semana_y_entradas(engine_sembrado: Engine) -> None:
    hogar = _hogar(engine_sembrado)
    (receta_a, _), (receta_b, _) = _recetas_completas(engine_sembrado)

    with Session(engine_sembrado) as session:
        plan = crear_plan(
            session, hogar, week_start=date(2026, 11, 25), budget_clp=60_000
        )
        assert plan["week_start"] == LUNES.isoformat()
        assert plan["week_end"] == "2026-11-29"
        assert plan["status"] == "draft"
        assert plan["entries"] == []

        with pytest.raises(PlanInvalido, match="Ya existe"):
            crear_plan(session, hogar, week_start=LUNES, budget_clp=10_000)

        detalle = definir_entrada(
            session,
            hogar,
            plan["plan_id"],
            fecha=LUNES,
            meal_slot="almuerzo",
            recipe_id=receta_a,
        )
        assert len(detalle["entries"]) == 1
        assert detalle["entries"][0]["recipe_title"]

        # El mismo día+slot se reemplaza (upsert), no se duplica.
        detalle = definir_entrada(
            session,
            hogar,
            plan["plan_id"],
            fecha=LUNES,
            meal_slot="almuerzo",
            recipe_id=receta_b,
            servings_multiplier=1.5,
        )
        assert len(detalle["entries"]) == 1
        assert detalle["entries"][0]["recipe_id"] == receta_b
        assert detalle["entries"][0]["servings_multiplier"] == 1.5

        libre = definir_entrada(
            session,
            hogar,
            plan["plan_id"],
            fecha=date(2026, 11, 27),
            meal_slot="cena",
            label="Noche libre: sobras",
            estimated_cost_clp=3_000,
        )
        assert libre["entries"][-1]["recipe_id"] is None
        assert libre["entries"][-1]["estimated_cost_clp"] == 3_000

        with pytest.raises(PlanInvalido, match="fuera de la semana"):
            definir_entrada(
                session,
                hogar,
                plan["plan_id"],
                fecha=date(2026, 11, 30),
                meal_slot="cena",
                recipe_id=receta_a,
            )
        with pytest.raises(PlanInvalido, match="label"):
            definir_entrada(
                session, hogar, plan["plan_id"], fecha=LUNES, meal_slot="cena"
            )
        with pytest.raises(PlanInvalido, match="Slot inválido"):
            definir_entrada(
                session,
                hogar,
                plan["plan_id"],
                fecha=LUNES,
                meal_slot="siesta",
                recipe_id=receta_a,
            )

        assert len(obtener_plan(session, hogar, plan["plan_id"])["entries"]) == 2


def test_estimacion_por_cadena_persiste_snapshots(engine_sembrado: Engine) -> None:
    hogar = _hogar(engine_sembrado)
    (receta_a, costo_a), (receta_b, costo_b) = _recetas_completas(engine_sembrado)

    with Session(engine_sembrado) as session:
        plan = crear_plan(session, hogar, week_start=LUNES, budget_clp=80_000)
        plan_id = plan["plan_id"]
        definir_entrada(
            session,
            hogar,
            plan_id,
            fecha=LUNES,
            meal_slot="almuerzo",
            recipe_id=receta_a,
        )
        definir_entrada(
            session,
            hogar,
            plan_id,
            fecha=date(2026, 11, 24),
            meal_slot="cena",
            recipe_id=receta_b,
            servings_multiplier=2,
        )
        definir_entrada(
            session,
            hogar,
            plan_id,
            fecha=date(2026, 11, 25),
            meal_slot="cena",
            label="Noche libre: llevar",
            estimated_cost_clp=4_500,
        )

        resultado = estimar_costo_plan(
            session, hogar, plan_id, store_ids=["jumbo", "santaisabel"]
        )
        assert [s["store_id"] for s in resultado["stores"]] == ["jumbo", "santaisabel"]
        assert resultado["budget_clp"] == 80_000

        jumbo = resultado["stores"][0]
        assert jumbo["is_complete"] is True
        assert len(jumbo["entries"]) == 3
        assert jumbo["total_clp"] == sum(e["cost_clp"] for e in jumbo["entries"])
        assert jumbo["total_clp"] >= costo_a + 2 * costo_b + 4_500
        assert jumbo["fetched_at"] and jumbo["snapshot_id"]

        snapshots = session.exec(
            select(BudgetSnapshot)
            .where(BudgetSnapshot.plan_id == plan_id)
            .order_by(BudgetSnapshot.id)
        ).all()
        assert len(snapshots) == 2
        assert {s.store_id for s in snapshots} == {"jumbo", "santaisabel"}
        assert snapshots[0].breakdown["entries"][0]["cost_clp"] >= 0
        assert snapshots[0].fetched_at is not None


def test_estado_presupuesto_excedido_y_estimado(engine_sembrado: Engine) -> None:
    hogar = _hogar(engine_sembrado)
    [(receta_a, costo_a)] = _recetas_completas(engine_sembrado, cantidad=1)

    with Session(engine_sembrado) as session:
        plan = crear_plan(session, hogar, week_start=LUNES, budget_clp=costo_a + 5_000)
        plan_id = plan["plan_id"]
        definir_entrada(
            session,
            hogar,
            plan_id,
            fecha=LUNES,
            meal_slot="almuerzo",
            recipe_id=receta_a,
        )

        # Sin snapshot previo: lo calcula y persiste al vuelo.
        estado = estado_presupuesto(session, hogar, plan_id, store_id="jumbo")
        assert estado["budget_clp"] == costo_a + 5_000
        assert estado["estimated_clp"] == costo_a
        assert estado["variance_clp"] == 5_000
        assert estado["budget_status"] == "ok"
        assert estado["is_complete"] is True
        assert estado["estimated_at"]

        # Bajar el presupuesto no reestima: el snapshot sigue vigente.
        sesion_plan = session.get(MealPlan, plan_id)
        sesion_plan.budget_clp = max(1, costo_a - 1_000)
        session.add(sesion_plan)
        session.commit()
        excedido = estado_presupuesto(session, hogar, plan_id, store_id="jumbo")
        assert excedido["variance_clp"] < 0
        assert excedido["budget_status"] == "over"
        assert excedido["snapshot_id"] == estado["snapshot_id"]


def test_api_planes_y_permisos(api_local: TestClient, engine_sembrado: Engine) -> None:
    [(receta_a, _)] = _recetas_completas(engine_sembrado, cantidad=1)

    registro = api_local.post(
        "/api/v1/auth/register",
        json={
            "email": "plan@example.cl",
            "password": PASSWORD,
            "display_name": "Plan",
            "privacy_consent": True,
        },
    )
    assert registro.status_code == 201, registro.text
    dueno = _bearer(registro.json()["token"])
    with Session(engine_sembrado) as session:
        usuario = session.exec(select(User).where(User.email == "plan@example.cl")).one()
        membresia = session.exec(
            select(HouseholdMember).where(HouseholdMember.user_id == usuario.id)
        ).one()
        hogar_api = membresia.household_id

    creado = api_local.post(
        "/api/v1/plans",
        headers=dueno,
        json={"week_start": LUNES.isoformat(), "budget_clp": 50_000},
    )
    assert creado.status_code == 201, creado.text
    plan_id = creado.json()["plan_id"]

    duplicado = api_local.post(
        "/api/v1/plans",
        headers=dueno,
        json={"week_start": "2026-11-24", "budget_clp": 50_000},
    )
    assert duplicado.status_code == 422
    assert "Ya existe" in duplicado.json()["detail"]

    entrada = api_local.put(
        f"/api/v1/plans/{plan_id}/entries",
        headers=dueno,
        json={
            "date": LUNES.isoformat(),
            "meal_slot": "almuerzo",
            "recipe_id": receta_a,
        },
    )
    assert entrada.status_code == 200, entrada.text
    assert entrada.json()["entries"][0]["recipe_id"] == receta_a

    estimado = api_local.post(
        f"/api/v1/plans/{plan_id}/estimate",
        headers=dueno,
        json={"store_ids": ["jumbo"]},
    )
    assert estimado.status_code == 200, estimado.text
    total = estimado.json()["stores"][0]["total_clp"]
    assert total > 0

    presupuesto = api_local.get(
        f"/api/v1/plans/{plan_id}/budget?store_id=jumbo", headers=dueno
    )
    assert presupuesto.status_code == 200
    datos = presupuesto.json()
    assert datos["estimated_clp"] == total
    assert datos["variance_clp"] == 50_000 - total

    listado = api_local.get("/api/v1/plans", headers=dueno)
    assert listado.status_code == 200
    assert listado.json()[0]["plan_id"] == plan_id
    assert api_local.get(
        f"/api/v1/plans/{plan_id}", headers=dueno
    ).status_code == 200

    viewer = _usuario(engine_sembrado, "viewer-plan@example.cl", Role.viewer, hogar_api)
    assert api_local.post(
        "/api/v1/plans",
        headers=_bearer(viewer),
        json={"week_start": "2026-11-16", "budget_clp": 50_000},
    ).status_code == 403
    assert api_local.get(
        f"/api/v1/plans/{plan_id}", headers=_bearer(viewer)
    ).status_code == 200


def test_tools_mcp_del_planificador(
    engine_sembrado: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    hogar = _hogar(engine_sembrado)
    [(receta_a, _)] = _recetas_completas(engine_sembrado, cantidad=1)
    monkeypatch.delenv("MCP_API_TOKEN", raising=False)
    set_mcp_engine(engine_sembrado)

    async def escenario() -> None:
        async with Client(mcp) as cliente:
            nombres = {t.name for t in await cliente.list_tools()}
            assert {
                "create_meal_plan",
                "set_meal_plan_entry",
                "delete_meal_plan_entry",
                "estimate_meal_plan_cost",
                "get_budget_status",
                "get_meal_plan",
                "list_meal_plans",
            } <= nombres

            previa = _json(
                await cliente.call_tool(
                    "create_meal_plan",
                    {"week_start": LUNES.isoformat(), "budget_clp": 50_000},
                )
            )
            assert previa["dry_run"] is True
            assert previa["week_end"] == "2026-11-29"

            plan = _json(
                await cliente.call_tool(
                    "create_meal_plan",
                    {
                        "week_start": LUNES.isoformat(),
                        "budget_clp": 50_000,
                        "dry_run": False,
                    },
                )
            )
            entrada = _json(
                await cliente.call_tool(
                    "set_meal_plan_entry",
                    {
                        "plan_id": plan["plan_id"],
                        "date": LUNES.isoformat(),
                        "meal_slot": "almuerzo",
                        "recipe_id": receta_a,
                    },
                )
            )
            assert entrada["entries"][0]["recipe_id"] == receta_a

            estimacion = _json(
                await cliente.call_tool(
                    "estimate_meal_plan_cost",
                    {"plan_id": plan["plan_id"], "store_ids": ["jumbo"]},
                )
            )
            estado = _json(
                await cliente.call_tool(
                    "get_budget_status",
                    {"plan_id": plan["plan_id"], "store_id": "jumbo"},
                )
            )
            assert estado["estimated_clp"] == estimacion["stores"][0]["total_clp"]
            assert estado["variance_clp"] == 50_000 - estado["estimated_clp"]

    try:
        asyncio.run(escenario())
    finally:
        set_mcp_engine(None)

    _usuario(engine_sembrado, "viewer-mcp@example.cl", Role.viewer, hogar)
    with Session(engine_sembrado) as session:
        usuario = session.exec(
            select(User).where(User.email == "viewer-mcp@example.cl")
        ).one()
        token = crear_token(session, usuario, name="viewer", scopes=["read"])["token"]

    monkeypatch.setenv("MCP_API_TOKEN", token)
    set_mcp_engine(engine_sembrado)

    async def rechazo() -> None:
        async with Client(mcp) as cliente:
            with pytest.raises(ToolError, match="write_draft"):
                await cliente.call_tool(
                    "create_meal_plan",
                    {"week_start": "2026-11-16", "budget_clp": 10_000},
                )

    try:
        asyncio.run(rechazo())
    finally:
        set_mcp_engine(None)
        monkeypatch.delenv("MCP_API_TOKEN", raising=False)


def test_budget_sugerencia_variedad_y_noche_libre(engine_sembrado: Engine) -> None:
    hogar = _hogar(engine_sembrado)
    enorme = 1_000_000
    with Session(engine_sembrado) as session:
        previa = sugerir_plan(
            session, hogar, week_start=LUNES, budget_clp=enorme, free_nights=1
        )
        cenas = [e for e in previa["entries"] if e["recipe_id"] is not None]
        libres = [e for e in previa["entries"] if e["recipe_id"] is None]
        assert len(previa["entries"]) == 7
        assert len(cenas) == 6 and len(libres) == 1
        assert libres[0]["meal_slot"] == "cena"
        assert libres[0]["estimated_cost_clp"] == 3_000
        assert len({e["recipe_id"] for e in cenas}) == 6
        assert previa["estimated_clp"] == sum(e["cost_clp"] for e in previa["entries"])
        assert previa["estimated_clp"] <= enorme
        assert previa["variance_clp"] == enorme - previa["estimated_clp"]

        # La receta más barata usada la semana anterior no puede repetirse.
        mas_barata = min(cenas, key=lambda e: e["cost_clp"])["recipe_id"]
        anterior = crear_plan(
            session,
            hogar,
            week_start=LUNES - timedelta(days=7),
            budget_clp=enorme,
        )
        definir_entrada(
            session,
            hogar,
            anterior["plan_id"],
            fecha=LUNES - timedelta(days=7),
            meal_slot="cena",
            recipe_id=mas_barata,
        )
        nueva = sugerir_plan(
            session, hogar, week_start=LUNES, budget_clp=enorme, variety_weeks=4
        )
        assert mas_barata not in {e["recipe_id"] for e in nueva["entries"]}
        sin_variedad = sugerir_plan(
            session,
            hogar,
            week_start=LUNES,
            budget_clp=enorme,
            variety_weeks=0,
        )
        assert mas_barata in {e["recipe_id"] for e in sin_variedad["entries"]}

        guardado = sugerir_plan(
            session,
            hogar,
            week_start=LUNES,
            budget_clp=enorme,
            free_nights=2,
            free_night_cost_clp=2_500,
            dry_run=False,
        )
        assert guardado["plan_id"] is not None
        assert guardado["status"] == "draft"
        plan = obtener_plan(session, hogar, guardado["plan_id"])
        assert len(plan["entries"]) == 7
        libres = [e for e in plan["entries"] if e["recipe_id"] is None]
        assert len(libres) == 2
        assert all(e["estimated_cost_clp"] == 2_500 for e in libres)
        assert guardado["estimated_clp"] == sum(
            e["cost_clp"] for e in guardado["entries"]
        )


def test_budget_sugerencia_presupuesto_insuficiente(engine_sembrado: Engine) -> None:
    hogar = _hogar(engine_sembrado)
    with Session(engine_sembrado) as session, pytest.raises(
        PresupuestoInsuficiente
    ) as excinfo:
        sugerir_plan(session, hogar, week_start=LUNES, budget_clp=1, free_nights=1)
    assert excinfo.value.minimo_clp > 1
    assert excinfo.value.presupuesto_clp == 1
    assert "plan mínimo" in str(excinfo.value)


def test_budget_confirm_scope_congela_y_rechaza_exceso(
    api_local: TestClient, engine_sembrado: Engine
) -> None:
    registro = api_local.post(
        "/api/v1/auth/register",
        json={
            "email": "confirm@example.cl",
            "password": PASSWORD,
            "display_name": "Confirm",
            "privacy_consent": True,
        },
    )
    assert registro.status_code == 201, registro.text
    login = registro.json()["token"]
    enorme = 1_000_000

    sugerido = api_local.post(
        "/api/v1/plans/suggest",
        headers=_bearer(login),
        json={
            "week_start": LUNES.isoformat(),
            "budget_clp": enorme,
            "free_nights": 1,
            "dry_run": False,
        },
    )
    assert sugerido.status_code == 200, sugerido.text
    plan_id = sugerido.json()["plan_id"]
    assert sugerido.json()["estimated_clp"] <= enorme

    sin_scope = api_local.post(
        f"/api/v1/plans/{plan_id}/confirm", headers=_bearer(login)
    )
    assert sin_scope.status_code == 403
    assert "confirm" in sin_scope.json()["detail"]

    token_confirm = api_local.post(
        "/api/v1/tokens",
        headers=_bearer(login),
        json={"name": "confirmador", "scopes": ["confirm"]},
    )
    assert token_confirm.status_code == 201, token_confirm.text
    headers = _bearer(token_confirm.json()["token"])

    confirmado = api_local.post(f"/api/v1/plans/{plan_id}/confirm", headers=headers)
    assert confirmado.status_code == 200, confirmado.text
    datos = confirmado.json()
    assert datos["status"] == "confirmed"
    assert datos["confirmed_at"]
    assert datos["budget"]["variance_clp"] >= 0

    entrada = api_local.put(
        f"/api/v1/plans/{plan_id}/entries",
        headers=headers,
        json={
            "date": LUNES.isoformat(),
            "meal_slot": "almuerzo",
            "recipe_id": 1,
        },
    )
    assert entrada.status_code == 422
    assert "no admite cambios" in entrada.json()["detail"]
    assert api_local.post(
        f"/api/v1/plans/{plan_id}/confirm", headers=headers
    ).status_code == 422

    with Session(engine_sembrado) as session:
        usuario = session.exec(
            select(User).where(User.email == "confirm@example.cl")
        ).one()
        membresia = session.exec(
            select(HouseholdMember).where(HouseholdMember.user_id == usuario.id)
        ).one()
        hogar = membresia.household_id
        apretado = crear_plan(
            session, hogar, week_start=LUNES + timedelta(days=7), budget_clp=1
        )
        [(receta, _)] = _recetas_completas(engine_sembrado, cantidad=1)
        definir_entrada(
            session,
            hogar,
            apretado["plan_id"],
            fecha=LUNES + timedelta(days=7),
            meal_slot="cena",
            recipe_id=receta,
        )
        with pytest.raises(PlanInvalido, match="excede el presupuesto"):
            confirmar_plan(session, hogar, apretado["plan_id"])


def test_budget_confirm_mcp_requiere_scope(
    engine_sembrado: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    hogar = _hogar(engine_sembrado)
    [(receta, _)] = _recetas_completas(engine_sembrado, cantidad=1)
    with Session(engine_sembrado) as session:
        plan = crear_plan(session, hogar, week_start=LUNES, budget_clp=1_000_000)
        definir_entrada(
            session,
            hogar,
            plan["plan_id"],
            fecha=LUNES,
            meal_slot="cena",
            recipe_id=receta,
        )
        _, usuario = owner_implicito(session)
        sin_confirm = crear_token(
            session, usuario, name="borrador", scopes=["read", "write_draft"]
        )["token"]
        con_confirm = crear_token(
            session, usuario, name="confirmador", scopes=["read", "confirm"]
        )["token"]

    set_mcp_engine(engine_sembrado)
    monkeypatch.setenv("MCP_API_TOKEN", sin_confirm)

    async def rechazo() -> None:
        async with Client(mcp) as cliente:
            with pytest.raises(ToolError, match="confirm"):
                await cliente.call_tool(
                    "confirm_meal_plan", {"plan_id": plan["plan_id"]}
                )

    try:
        asyncio.run(rechazo())
    finally:
        set_mcp_engine(None)

    monkeypatch.setenv("MCP_API_TOKEN", con_confirm)
    set_mcp_engine(engine_sembrado)

    async def confirma() -> dict[str, Any]:
        async with Client(mcp) as cliente:
            resultado = await cliente.call_tool(
                "confirm_meal_plan", {"plan_id": plan["plan_id"]}
            )
            return _json(resultado)

    try:
        datos = asyncio.run(confirma())
    finally:
        set_mcp_engine(None)
        monkeypatch.delenv("MCP_API_TOKEN", raising=False)

    assert datos["status"] == "confirmed"
    assert datos["confirmed_at"]


def test_intercambiar_comida_api(api_local: TestClient, engine_sembrado: Engine) -> None:
    """Swap: intercambio de receta y reequilibrio de presupuesto."""
    registro = api_local.post(
        "/api/v1/auth/register",
        json={
            "email": "swap@example.cl",
            "password": PASSWORD,
            "display_name": "Swap",
            "privacy_consent": True,
        },
    )
    assert registro.status_code == 201, registro.text
    (receta_a, _), (receta_b, _), (receta_c, _) = _recetas_completas(
        engine_sembrado, cantidad=3
    )

    token = registro.json()["token"]
    headers = _bearer(token)

    # Crear plan vía API
    plan_resp = api_local.post(
        "/api/v1/plans",
        headers=headers,
        json={"week_start": LUNES.isoformat(), "budget_clp": 100_000},
    )
    assert plan_resp.status_code == 201, plan_resp.text
    plan_id = plan_resp.json()["plan_id"]

    # Agregar entradas vía API
    entr1 = api_local.put(
        f"/api/v1/plans/{plan_id}/entries",
        headers=headers,
        json={
            "date": LUNES.isoformat(),
            "meal_slot": "cena",
            "recipe_id": receta_a,
        },
    )
    assert entr1.status_code == 200, entr1.text

    entr2 = api_local.put(
        f"/api/v1/plans/{plan_id}/entries",
        headers=headers,
        json={
            "date": (LUNES + timedelta(days=1)).isoformat(),
            "meal_slot": "cena",
            "recipe_id": receta_b,
        },
    )
    assert entr2.status_code == 200, entr2.text

    # Intercambio: cambiar cena de lunes por receta_c
    swap = api_local.post(
        f"/api/v1/plans/{plan_id}/entries/1/swap",
        headers=headers,
        json={"new_recipe_id": receta_c},
    )
    assert swap.status_code == 200, swap.text
    data = swap.json()
    assert data["swap"]["to_recipe_id"] == receta_c
    assert data["swap"]["from_recipe_id"] == receta_a
    assert isinstance(data["rebalance"]["applied"], bool)


def test_intercambiar_comida_service(engine_sembrado: Engine) -> None:
    """Intercambio de receta con reequilibrio automático."""
    hogar = _hogar(engine_sembrado)
    enorme = 1_000_000
    (receta_a, _), (receta_b, _), (receta_c, _) = _recetas_completas(
        engine_sembrado, cantidad=3
    )

    with Session(engine_sembrado) as session:
        plan = crear_plan(session, hogar, week_start=LUNES, budget_clp=enorme)
        plan_id = plan["plan_id"]

        # 5 cenas + 2 noches libres = gasto esperado
        definir_entrada(
            session,
            hogar,
            plan_id,
            fecha=LUNES,
            meal_slot="cena",
            recipe_id=receta_a,
        )
        definir_entrada(
            session,
            hogar,
            plan_id,
            fecha=LUNES + timedelta(days=1),
            meal_slot="cena",
            recipe_id=receta_b,
        )
        definir_entrada(
            session,
            hogar,
            plan_id,
            fecha=LUNES + timedelta(days=6),
            meal_slot="cena",
            label="Noche libre",
            estimated_cost_clp=5_000,
        )

        # Intercambiar una receta por más cara y ver reequilibrio
        resultado = intercambiar_comida(
            session,
            hogar,
            plan_id,
            entry_id=1,
            new_recipe_id=receta_c,
        )
        assert resultado["swap"]["from_recipe_id"] == receta_a
        assert resultado["swap"]["to_recipe_id"] == receta_c
        assert isinstance(resultado["rebalance"]["applied"], bool)


def test_intercambiar_reequilibra_con_presupuesto_corto(
    engine_sembrado: Engine,
) -> None:
    """Swap que excede presupuesto dispara reequilibrio automático."""
    hogar = _hogar(engine_sembrado)
    (receta_a, costo_a), (receta_b, costo_b), (receta_c, costo_c) = _recetas_completas(
        engine_sembrado, cantidad=3
    )

    with Session(engine_sembrado) as session:
        # Presupuesto justo para 2 recetas + noche libre, sin margen
        plan = crear_plan(
            session,
            hogar,
            week_start=LUNES,
            budget_clp=costo_a + costo_b + 5_000 + 2_000,  # margen pequeño
        )
        plan_id = plan["plan_id"]

        definir_entrada(
            session,
            hogar,
            plan_id,
            fecha=LUNES,
            meal_slot="cena",
            recipe_id=receta_a,
        )
        definir_entrada(
            session,
            hogar,
            plan_id,
            fecha=LUNES + timedelta(days=1),
            meal_slot="cena",
            recipe_id=receta_b,
        )
        definir_entrada(
            session,
            hogar,
            plan_id,
            fecha=LUNES + timedelta(days=6),
            meal_slot="cena",
            label="Noche libre",
            estimated_cost_clp=5_000,
        )

        # Swap a receta más cara debería disparar reequilibrio
        resultado = intercambiar_comida(
            session,
            hogar,
            plan_id,
            entry_id=1,
            new_recipe_id=receta_c,
        )

        # Verificar reequilibrio aplicado
        assert resultado["plan_cost_clp"] <= resultado["budget_clp"]
        assert resultado["delta_vs_budget_clp"] >= 0
        assert resultado["rebalance"]["applied"] is True
        assert len(resultado["rebalance"]["changes"]) > 0

        # Verificar que el swap se aplicó correctamente
        assert resultado["swap"]["to_recipe_id"] == receta_c
        assert isinstance(resultado["rebalance"]["changes"], list)
