# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests del modelo de datos completo (spec §5).

Todos los tests corren sobre la MIGRACIÓN REAL de Alembic (fixture
`migrated_engine`), no sobre `SQLModel.metadata.create_all`: así se valida
exactamente lo que el entrypoint del contenedor aplicará en producción.
"""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db import get_engine
from app.models import (
    ApiToken,
    BudgetSnapshot,
    Expense,
    ExpenseCategory,
    ExpenseItem,
    Household,
    HouseholdMember,
    HouseholdPreference,
    Invitation,
    MealPlan,
    MealPlanEntry,
    PantryItem,
    PantryMovement,
    PriceSnapshot,
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
    StoreConnector,
    User,
)
from app.models.enums import (
    Difficulty,
    ImportSourceType,
    ListStatus,
    MealSlot,
    MovementReason,
    PantryLocation,
    PlanStatus,
    PriceConfidence,
    PriceSource,
    Role,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Las 27 tablas del resumen de la spec §5.
TABLAS_ESPERADAS = {
    "users", "households", "household_members", "household_preferences", "invitations",
    "product_catalog", "recipes", "recipe_ingredients", "recipe_steps", "recipe_tags",
    "recipe_ratings", "recipe_collections", "recipe_collection_items", "recipe_import_jobs",
    "pantry_items", "pantry_movements", "meal_plans", "meal_plan_entries", "budget_snapshots",
    "shopping_lists", "shopping_list_items", "price_snapshots", "store_connectors",
    "expenses", "expense_items", "expense_categories", "api_tokens",
}


def _alembic_config(db_url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def crear_grafo_completo(session: Session) -> dict[str, object]:
    """Inserta un registro en cada una de las 27 tablas, conectado por FKs."""
    user = User(email="dana@ejemplo.cl", display_name="Dana")
    household = Household(name="Hogar Prueba", default_weekly_budget_clp=45000)
    producto = ProductCatalog(
        canonical_name="palta",
        category="frutas",
        default_unit="unidad",
        purchase_unit="unidad",
        purchase_size=1.0,
        aliases=["aguacate", "palta hass"],
    )
    cadena = StoreConnector(name="jumbo", type="mcp-supermercados-cl", enabled=True, config={})
    categoria = ExpenseCategory(name="Supermercado")

    for obj in (user, household, producto, cadena, categoria):
        session.add(obj)
    session.flush()

    miembro = HouseholdMember(household_id=household.id, user_id=user.id, role=Role.owner)
    preferencias = HouseholdPreference(household_id=household.id, comuna="Providencia")
    invitacion = Invitation(
        household_id=household.id,
        code="ABC123XYZ",
        created_by=user.id,
        expires_at=datetime(2026, 11, 18, 12, 0, tzinfo=UTC),
    )
    token = ApiToken(
        user_id=user.id,
        name="home-assistant",
        token_hash="argon2id$hash-de-ejemplo",
        scopes=["read", "write_draft"],
    )
    receta = Recipe(
        household_id=household.id,
        title="Cazuela de vacuno",
        base_servings=4,
        prep_minutes=20,
        cook_minutes=90,
        difficulty=Difficulty.media,
        instructions="1. Sofreír las verduras...",
        created_by=user.id,
    )
    for obj in (miembro, preferencias, invitacion, token, receta):
        session.add(obj)
    session.flush()

    ingrediente = RecipeIngredient(
        recipe_id=receta.id, product_id=producto.id, quantity=500.0, unit="g"
    )
    paso = RecipeStep(
        recipe_id=receta.id, step_number=1, instruction="Sofreír cebolla y zapallo",
        duration_minutes=10,
    )
    etiqueta = RecipeTag(recipe_id=receta.id, tag="casera")
    calificacion = RecipeRating(recipe_id=receta.id, user_id=user.id, rating=5)
    coleccion = RecipeCollection(household_id=household.id, name="Favoritas")
    job = RecipeImportJob(
        household_id=household.id,
        source_type=ImportSourceType.url,
        source_value="https://ejemplo.cl/receta",
    )
    despensa = PantryItem(
        household_id=household.id,
        product_id=producto.id,
        quantity=3.0,
        unit="unidad",
        location=PantryLocation.refrigerador,
    )
    plan = MealPlan(
        household_id=household.id,
        week_start=date(2026, 11, 23),
        budget_clp=45000,
        status=PlanStatus.draft,
        created_by=user.id,
    )
    for obj in (ingrediente, paso, etiqueta, calificacion, coleccion, job, despensa, plan):
        session.add(obj)
    session.flush()

    item_coleccion = RecipeCollectionItem(collection_id=coleccion.id, recipe_id=receta.id)
    movimiento = PantryMovement(
        pantry_item_id=despensa.id,
        delta=-1.0,
        reason=MovementReason.recipe_consumption,
        reference_id=str(receta.id),
    )
    entrada = MealPlanEntry(
        plan_id=plan.id,
        date=date(2026, 11, 23),
        meal_slot=MealSlot.cena,
        recipe_id=receta.id,
        servings_multiplier=1.5,
    )
    snapshot = BudgetSnapshot(
        plan_id=plan.id, store_id="jumbo", total_clp=41250, breakdown={"cena": 41250}
    )
    lista = ShoppingList(
        household_id=household.id, plan_id=plan.id, name="Semana 2026-11-23",
        status=ListStatus.active,
    )
    precio = PriceSnapshot(
        product_id=producto.id,
        store_id="jumbo",
        price_clp=1500,
        unit_price_clp=1500,
        source=PriceSource.live,
        confidence=PriceConfidence.high,
    )
    gasto = Expense(
        household_id=household.id,
        store_id="jumbo",
        amount_clp=38000,
        date=date(2026, 11, 23),
        category_id=categoria.id,
    )
    for obj in (item_coleccion, movimiento, entrada, snapshot, lista, precio, gasto):
        session.add(obj)
    session.flush()

    session.add(
        ShoppingListItem(
            list_id=lista.id, product_id=producto.id, required_quantity=2.0, unit="unidad"
        )
    )
    session.add(
        ExpenseItem(expense_id=gasto.id, product_id=producto.id, quantity=2.0, unit_price_clp=1500)
    )
    session.commit()

    # IDs primitivos: las instancias quedan detached al cerrar la sesión.
    return {
        "user_id": user.id,
        "household_id": household.id,
        "receta_id": receta.id,
        "plan_id": plan.id,
        "lista_id": lista.id,
    }


def test_la_migracion_crea_las_27_tablas(migrated_engine) -> None:
    tablas = set(inspect(migrated_engine).get_table_names())
    assert len(TABLAS_ESPERADAS) == 27
    assert TABLAS_ESPERADAS <= tablas, f"faltan: {TABLAS_ESPERADAS - tablas}"


def test_indices_criticos_de_la_spec(migrated_engine) -> None:
    inspector = inspect(migrated_engine)

    def columnas(tabla: str, indice: str) -> list[str] | None:
        for ix in inspector.get_indexes(tabla):
            if ix["name"] == indice:
                return list(ix["column_names"])
        return None

    assert columnas("price_snapshots", "ix_price_snapshots_lookup") == [
        "product_id", "store_id", "fetched_at",
    ]
    assert columnas("meal_plan_entries", "ix_meal_plan_entries_plan_date") == ["plan_id", "date"]
    assert columnas("pantry_items", "ix_pantry_items_lookup") == ["household_id", "product_id"]
    assert columnas("shopping_list_items", "ix_shopping_list_items_checked") == [
        "list_id", "checked"
    ]


def test_smoke_un_registro_por_cada_tabla(migrated_engine) -> None:
    with Session(migrated_engine) as session:
        objs = crear_grafo_completo(session)

    with Session(migrated_engine) as session:
        receta = session.get(Recipe, objs["receta_id"])
        assert receta is not None
        assert receta.title == "Cazuela de vacuno"
        assert receta.difficulty is Difficulty.media

        for tabla in sorted(TABLAS_ESPERADAS):
            n = session.execute(text(f"SELECT COUNT(*) FROM {tabla}")).scalar_one()
            assert n >= 1, f"la tabla {tabla} quedó vacía"


def test_enums_se_persisten_con_valores_limpios(migrated_engine) -> None:
    with Session(migrated_engine) as session:
        crear_grafo_completo(session)

    with Session(migrated_engine) as session:
        fila = session.execute(
            text("SELECT source, confidence, role FROM price_snapshots "
                 "JOIN household_members ON 1=1 LIMIT 1")
        ).one()
        assert fila.source == "live"
        assert fila.confidence == "high"
        assert fila.role == "owner"

        snap = session.exec(select(PriceSnapshot)).one()
        assert snap.source is PriceSource.live
        assert snap.confidence is PriceConfidence.high


def test_un_plan_por_hogar_y_semana(migrated_engine) -> None:
    with Session(migrated_engine) as session:
        hogar = Household(name="Hogar A")
        session.add(hogar)
        session.flush()

        session.add(
            MealPlan(household_id=hogar.id, week_start=date(2026, 11, 23), budget_clp=45000)
        )
        session.commit()

        session.add(
            MealPlan(household_id=hogar.id, week_start=date(2026, 11, 23), budget_clp=50000)
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        # Otra semana del mismo hogar sí está permitida.
        session.add(
            MealPlan(household_id=hogar.id, week_start=date(2026, 11, 30), budget_clp=45000)
        )
        session.commit()


def test_un_rating_por_usuario_y_receta(migrated_engine) -> None:
    with Session(migrated_engine) as session:
        user = User(email="una@ejemplo.cl", display_name="Una")
        hogar = Household(name="Hogar B")
        receta = Recipe(title="Charquicán")
        session.add_all([user, hogar, receta])
        session.flush()

        session.add(RecipeRating(recipe_id=receta.id, user_id=user.id, rating=4))
        session.commit()

        session.add(RecipeRating(recipe_id=receta.id, user_id=user.id, rating=3))
        with pytest.raises(IntegrityError):
            session.commit()


def test_rating_fuera_de_rango_rechazado(migrated_engine) -> None:
    """El CHECK de la migración debe exigir rating entre 1 y 5 (spec §3.2)."""
    with Session(migrated_engine) as session:
        user = User(email="dos@ejemplo.cl", display_name="Dos")
        receta = Recipe(title="Porotos con riendas")
        session.add_all([user, receta])
        session.flush()

        session.add(RecipeRating(recipe_id=receta.id, user_id=user.id, rating=6))
        with pytest.raises(IntegrityError):
            session.commit()


def test_ciclo_downgrade_base_y_upgrade_head(tmp_path: Path) -> None:
    """AC de la Task 3: upgrade → downgrade base → upgrade, todo idempotente."""
    db_url = f"sqlite:///{tmp_path.as_posix()}/ciclo.sqlite3"
    cfg = _alembic_config(db_url)

    command.upgrade(cfg, "head")
    engine = get_engine(db_url)
    with Session(engine) as session:
        session.add(Household(name="Hogar 1"))
        session.commit()
    engine.dispose()

    command.downgrade(cfg, "base")
    engine2 = get_engine(db_url)
    assert "households" not in set(inspect(engine2).get_table_names())
    engine2.dispose()

    command.upgrade(cfg, "head")
    engine3 = get_engine(db_url)
    with Session(engine3) as session:
        session.add(Household(name="Hogar 2"))
        session.commit()
        assert len(session.exec(select(Household)).all()) == 1  # la base quedó limpia
    engine3.dispose()
