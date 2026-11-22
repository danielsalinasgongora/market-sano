# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests de hogares, miembros, roles, invitaciones y supresión (Task 14)."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.main import create_app
from app.models import (
    BudgetSnapshot,
    Expense,
    ExpenseItem,
    Household,
    HouseholdMember,
    HouseholdPreference,
    Invitation,
    MealPlan,
    MealPlanEntry,
    PantryItem,
    PantryMovement,
    ProductCatalog,
    Recipe,
    RecipeCollection,
    RecipeCollectionItem,
    RecipeImportJob,
    RecipeIngredient,
    RecipeRating,
    RecipeStep,
    RecipeTag,
    ShoppingList,
    ShoppingListItem,
    User,
)
from app.models.enums import (
    ImportSourceType,
    ImportStatus,
    MealSlot,
    MovementReason,
    PlanStatus,
    Role,
)
from app.seed import seed
from app.services.auth import PRIVACY_NOTICE_VERSION
from app.settings import Settings

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


def _registrar(api: TestClient, email: str, nombre: str) -> dict[str, Any]:
    r = api.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "display_name": nombre,
            "privacy_consent": True,
            "privacy_notice_version": PRIVACY_NOTICE_VERSION,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _headers(sesion: dict[str, Any], household_id: int | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {sesion['token']}"}
    if household_id is not None:
        headers["X-Household-Id"] = str(household_id)
    return headers


def _invitar(api: TestClient, sesion: dict[str, Any], household_id: int) -> str:
    r = api.post(
        f"/api/v1/households/{household_id}/invitations",
        headers=_headers(sesion, household_id),
        json={"ttl_hours": 24},
    )
    assert r.status_code == 201, r.text
    return r.json()["code"]


def _unir(api: TestClient, sesion: dict[str, Any], codigo: str) -> Any:
    return api.post(
        "/api/v1/households/join",
        headers=_headers(sesion),
        json={"code": codigo},
    )


def test_registro_crea_hogar_owner_e_invitacion_une_como_member(
    api_local: TestClient, engine_sembrado: Engine
) -> None:
    ana = _registrar(api_local, "ana@example.cl", "Ana")
    hogar = ana["user"]["household_id"]
    assert ana["user"]["role"] == "owner"
    assert hogar is not None

    codigo = _invitar(api_local, ana, hogar)
    assert len(codigo) == 10 and codigo.isalnum()

    beto = _registrar(api_local, "beto@example.cl", "Beto")
    union = _unir(api_local, beto, codigo.lower())  # el código no distingue mayúsculas
    assert union.status_code == 200, union.text
    assert union.json() == {"household_id": hogar, "name": "Hogar de Ana", "role": "member"}

    hogares = api_local.get("/api/v1/households", headers=_headers(beto))
    assert hogares.status_code == 200
    compartido = [h for h in hogares.json() if h["household_id"] == hogar]
    assert compartido and compartido[0]["role"] == "member"
    assert compartido[0]["member_count"] == 2
    # Beto conserva además el hogar propio creado al registrarse.
    assert len(hogares.json()) == 2

    miembros = api_local.get(
        f"/api/v1/households/{hogar}/members", headers=_headers(ana, hogar)
    )
    assert miembros.status_code == 200
    assert {(m["email"], m["role"]) for m in miembros.json()} == {
        ("ana@example.cl", "owner"),
        ("beto@example.cl", "member"),
    }

    # El código es de un solo uso.
    reuso = _unir(api_local, beto, codigo)
    assert reuso.status_code == 422
    assert "ya fue utilizado" in reuso.json()["detail"]

    # Código inexistente.
    invalido = _unir(api_local, beto, "NOEXISTE1")
    assert invalido.status_code == 422
    assert "inválido" in invalido.json()["detail"]

    # Código expirado.
    carla = _registrar(api_local, "carla@example.cl", "Carla")
    with Session(engine_sembrado) as session:
        session.add(
            Invitation(
                household_id=hogar,
                code="EXPIRADO01",
                expires_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
        session.commit()
    expirado = _unir(api_local, carla, "EXPIRADO01")
    assert expirado.status_code == 422
    assert "expiró" in expirado.json()["detail"]

    with Session(engine_sembrado) as session:
        usada = session.exec(select(Invitation).where(Invitation.code == codigo)).one()
        assert usada.used_at is not None


def test_permisos_por_rol_viewer_member_owner(
    api_local: TestClient, engine_sembrado: Engine
) -> None:
    ana = _registrar(api_local, "ana@example.cl", "Ana")
    hogar = ana["user"]["household_id"]

    beto = _registrar(api_local, "beto@example.cl", "Beto")
    assert _unir(api_local, beto, _invitar(api_local, ana, hogar)).status_code == 200

    carla = _registrar(api_local, "carla@example.cl", "Carla")
    assert _unir(api_local, carla, _invitar(api_local, ana, hogar)).status_code == 200
    with Session(engine_sembrado) as session:
        fila = session.exec(
            select(HouseholdMember).where(
                HouseholdMember.household_id == hogar,
                HouseholdMember.user_id
                == session.exec(select(User).where(User.email == "carla@example.cl")).one().id,
            )
        ).one()
        fila.role = Role.viewer
        session.add(fila)
        session.commit()

    receta = {
        "title": "Receta del hogar",
        "ingredients": [{"product": "papa", "quantity": 1, "unit": "kg"}],
    }

    # Viewer: lee, pero no escribe ni administra.
    assert api_local.get(
        f"/api/v1/households/{hogar}/preferences", headers=_headers(carla, hogar)
    ).status_code == 200
    assert api_local.get("/api/v1/recipes", headers=_headers(carla)).status_code == 200
    for respuesta in (
        api_local.put(
            f"/api/v1/households/{hogar}/preferences",
            headers=_headers(carla, hogar),
            json={"comuna": "Providencia"},
        ),
        api_local.post(
            "/api/v1/recipes", headers=_headers(carla, hogar), json=receta
        ),
        api_local.post(
            f"/api/v1/households/{hogar}/invitations",
            headers=_headers(carla, hogar),
            json={},
        ),
        api_local.delete(
            f"/api/v1/households/{hogar}", headers=_headers(carla, hogar)
        ),
    ):
        assert respuesta.status_code == 403, respuesta.text
        assert "viewer" in respuesta.json()["detail"]

    # Member: escribe recetas y preferencias, invita; no borra el hogar.
    assert api_local.put(
        f"/api/v1/households/{hogar}/preferences",
        headers=_headers(beto, hogar),
        json={"comuna": "Ñuñoa", "never_buy": ["Bebida"]},
    ).status_code == 200
    assert api_local.post(
        "/api/v1/recipes", headers=_headers(beto, hogar), json=receta
    ).status_code == 201
    assert api_local.post(
        f"/api/v1/households/{hogar}/invitations",
        headers=_headers(beto, hogar),
        json={},
    ).status_code == 201
    borrado_member = api_local.delete(
        f"/api/v1/households/{hogar}", headers=_headers(beto, hogar)
    )
    assert borrado_member.status_code == 403
    assert "owner" in borrado_member.json()["detail"]

    # Owner: todo, incluidas las preferencias.
    prefs = api_local.put(
        f"/api/v1/households/{hogar}/preferences",
        headers=_headers(ana, hogar),
        json={"default_store_id": "jumbo", "dietary_restrictions": ["vegetariana"]},
    )
    assert prefs.status_code == 200, prefs.text
    assert prefs.json()["default_store_id"] == "jumbo"
    assert prefs.json()["dietary_restrictions"] == ["vegetariana"]
    # Beto escribió en el mismo hogar: sus cambios se conservan.
    assert prefs.json()["comuna"] == "Ñuñoa"
    assert prefs.json()["never_buy"] == ["bebida"]

    # La receta de Beto no es visible como privada desde el hogar propio de Carla.
    with Session(engine_sembrado) as session:
        receta_beto = session.exec(
            select(Recipe).where(
                Recipe.household_id == hogar, Recipe.title == "Receta del hogar"
            )
        ).first()
    assert receta_beto is not None
    privada = api_local.get(
        f"/api/v1/recipes/{receta_beto.id}", headers=_headers(carla)
    )
    assert privada.status_code == 404


def test_mcp_update_household_preferences(
    api_local: TestClient, engine_sembrado: Engine
) -> None:
    import asyncio
    import json

    from fastmcp import Client
    from sqlmodel import select

    from app.mcp.db import set_mcp_engine
    from app.mcp_server import mcp

    ana = _registrar(api_local, "ana@example.cl", "Ana")
    assert ana["user"]["role"] == "owner"

    set_mcp_engine(engine_sembrado)

    async def ejercitar() -> dict[str, Any]:
        async with Client(mcp) as cliente:
            nombres = {t.name for t in await cliente.list_tools()}
            assert "update_household_preferences" in nombres
            assert "get_household_preferences" in nombres
            resultado = await cliente.call_tool(
                "update_household_preferences",
                {"default_store_id": "unimarc", "allergies": ["Maní"]},
            )
            return json.loads(resultado.content[0].text)

    try:
        contenido = asyncio.run(ejercitar())
    finally:
        set_mcp_engine(None)

    assert contenido["default_store_id"] == "unimarc"
    assert contenido["allergies"] == ["maní"]

    with Session(engine_sembrado) as session:
        hogar = session.exec(select(Household).order_by(Household.id)).first()
        assert hogar is not None
        fila = session.get(HouseholdPreference, hogar.id)
        assert fila is not None and fila.default_store_id == "unimarc"


def test_delete_household_borra_datos_dependientes(
    api_local: TestClient, engine_sembrado: Engine
) -> None:
    ana = _registrar(api_local, "ana@example.cl", "Ana")
    hogar = ana["user"]["household_id"]
    beto = _registrar(api_local, "beto@example.cl", "Beto")
    assert _unir(api_local, beto, _invitar(api_local, ana, hogar)).status_code == 200

    with Session(engine_sembrado) as session:
        usuario = session.exec(select(User).where(User.email == "ana@example.cl")).one()
        producto = session.exec(select(ProductCatalog)).first()
        assert producto is not None

        receta = Recipe(household_id=hogar, title="Privada a borrar")
        session.add(receta)
        session.flush()
        session.add(
            RecipeIngredient(
                recipe_id=receta.id, product_id=producto.id, quantity=1, unit="kg"
            )
        )
        session.add(RecipeStep(recipe_id=receta.id, step_number=1, instruction="Cocinar"))
        session.add(RecipeTag(recipe_id=receta.id, tag="prueba"))
        session.add(RecipeRating(recipe_id=receta.id, user_id=usuario.id, rating=5))

        coleccion = RecipeCollection(household_id=hogar, name="Favoritas")
        session.add(coleccion)
        session.flush()
        session.add(
            RecipeCollectionItem(collection_id=coleccion.id, recipe_id=receta.id)
        )
        session.add(
            RecipeImportJob(
                household_id=hogar,
                source_type=ImportSourceType.url,
                source_value="https://example.cl/receta",
                status=ImportStatus.completed,
            )
        )

        plan = MealPlan(
            household_id=hogar,
            week_start=date(2026, 11, 23),
            budget_clp=50000,
            status=PlanStatus.draft,
        )
        session.add(plan)
        session.flush()
        session.add(
            MealPlanEntry(
                plan_id=plan.id,
                date=date(2026, 11, 23),
                meal_slot=MealSlot.almuerzo,
                recipe_id=receta.id,
            )
        )
        session.add(
            BudgetSnapshot(plan_id=plan.id, store_id="jumbo", total_clp=12000)
        )

        lista = ShoppingList(household_id=hogar, plan_id=plan.id, name="Semana")
        session.add(lista)
        session.flush()
        session.add(
            ShoppingListItem(
                list_id=lista.id,
                product_id=producto.id,
                required_quantity=1,
                unit="kg",
            )
        )

        despensa = PantryItem(
            household_id=hogar, product_id=producto.id, quantity=2, unit="kg"
        )
        session.add(despensa)
        session.flush()
        session.add(
            PantryMovement(
                pantry_item_id=despensa.id, delta=-1, reason=MovementReason.recipe_consumption
            )
        )

        gasto = Expense(household_id=hogar, amount_clp=15000, date=date(2026, 11, 22))
        session.add(gasto)
        session.flush()
        session.add(
            ExpenseItem(
                expense_id=gasto.id,
                product_id=producto.id,
                quantity=1,
                unit="kg",
                unit_price_clp=1500,
            )
        )
        session.add(HouseholdPreference(household_id=hogar, comuna="Providencia"))
        session.commit()

        ids = {
            "receta": receta.id,
            "plan": plan.id,
            "lista": lista.id,
            "despensa": despensa.id,
            "gasto": gasto.id,
        }
        recetas_publicas = len(
            session.exec(select(Recipe).where(Recipe.household_id.is_(None))).all()
        )
        productos = len(session.exec(select(ProductCatalog)).all())

    # Un member no puede suprimir el hogar.
    prohibido = api_local.delete(
        f"/api/v1/households/{hogar}", headers=_headers(beto, hogar)
    )
    assert prohibido.status_code == 403

    borrado = api_local.delete(
        f"/api/v1/households/{hogar}", headers=_headers(ana, hogar)
    )
    assert borrado.status_code == 204, borrado.text

    with Session(engine_sembrado) as session:
        assert session.get(Household, hogar) is None
        assert session.exec(
            select(HouseholdMember).where(HouseholdMember.household_id == hogar)
        ).all() == []
        for modelo in (
            Recipe,
            RecipeCollection,
            RecipeImportJob,
            MealPlan,
            ShoppingList,
            PantryItem,
            Expense,
            HouseholdPreference,
            Invitation,
        ):
            assert session.exec(
                select(modelo).where(modelo.household_id == hogar)
            ).all() == [], modelo.__name__
        for modelo in (
            RecipeIngredient,
            RecipeStep,
            RecipeTag,
            RecipeRating,
            RecipeCollectionItem,
        ):
            assert session.exec(
                select(modelo).where(modelo.recipe_id == ids["receta"])
            ).all() == [], modelo.__name__
        assert session.exec(
            select(MealPlanEntry).where(MealPlanEntry.plan_id == ids["plan"])
        ).all() == []
        assert session.exec(
            select(BudgetSnapshot).where(BudgetSnapshot.plan_id == ids["plan"])
        ).all() == []
        assert session.exec(
            select(ShoppingListItem).where(ShoppingListItem.list_id == ids["lista"])
        ).all() == []
        assert session.exec(
            select(PantryMovement).where(
                PantryMovement.pantry_item_id == ids["despensa"]
            )
        ).all() == []
        assert session.exec(
            select(ExpenseItem).where(ExpenseItem.expense_id == ids["gasto"])
        ).all() == []

        # El catálogo y las recetas públicas/comunitarias se conservan.
        publicas = session.exec(
            select(Recipe).where(Recipe.household_id.is_(None))
        ).all()
        assert len(publicas) == recetas_publicas
        assert len(session.exec(select(ProductCatalog)).all()) == productos

    assert api_local.get("/api/v1/households", headers=_headers(ana)).json() == []
    assert api_local.delete(
        f"/api/v1/households/{hogar}", headers=_headers(ana)
    ).status_code == 404
