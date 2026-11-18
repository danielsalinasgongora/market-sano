# SPDX-License-Identifier: GPL-3.0-or-later
"""Modelo de datos completo de Market Sano (spec §5).

Importar este paquete registra todas las tablas en `SQLModel.metadata`,
que es lo que consume Alembic (migrations/env.py) y la API.

Decisiones:
- `users.id` es UUID (spec §3.1); el resto de las tablas usa enteros.
- Los `*_at` se guardan en UTC (ver app.models.common).
- Campos JSON de la spec (JSONB) usan sa.JSON, portable SQLite/Postgres.
- `store_id` es string ("jumbo", "santaisabel", ...) alineado con el
  conector mcp-supermercados-cl; el registry vive en `store_connectors`.
"""

from app.models.catalog import PriceSnapshot, ProductCatalog, ProductStoreMatch, StoreConnector
from app.models.common import utcnow
from app.models.enums import (
    Difficulty,
    ImportSourceType,
    ImportStatus,
    ListStatus,
    MealSlot,
    MovementReason,
    PantryLocation,
    PlanStatus,
    PriceConfidence,
    PriceSource,
    Role,
)
from app.models.expenses import Expense, ExpenseCategory, ExpenseItem
from app.models.household import (
    ApiToken,
    Household,
    HouseholdMember,
    HouseholdPreference,
    Invitation,
    User,
)
from app.models.pantry import PantryItem, PantryMovement
from app.models.planning import (
    BudgetSnapshot,
    MealPlan,
    MealPlanEntry,
    ShoppingList,
    ShoppingListItem,
)
from app.models.recipes import (
    Recipe,
    RecipeCollection,
    RecipeCollectionItem,
    RecipeImportJob,
    RecipeIngredient,
    RecipeRating,
    RecipeStep,
    RecipeTag,
)

__all__ = [
    "ApiToken",
    "BudgetSnapshot",
    "Difficulty",
    "Expense",
    "ExpenseCategory",
    "ExpenseItem",
    "Household",
    "HouseholdMember",
    "HouseholdPreference",
    "ImportSourceType",
    "ImportStatus",
    "Invitation",
    "ListStatus",
    "MealPlan",
    "MealPlanEntry",
    "MealSlot",
    "MovementReason",
    "PantryItem",
    "PantryLocation",
    "PantryMovement",
    "PlanStatus",
    "PriceConfidence",
    "PriceSnapshot",
    "PriceSource",
    "ProductCatalog",
    "ProductStoreMatch",
    "Recipe",
    "RecipeCollection",
    "RecipeCollectionItem",
    "RecipeImportJob",
    "RecipeIngredient",
    "RecipeRating",
    "RecipeStep",
    "RecipeTag",
    "Role",
    "ShoppingList",
    "ShoppingListItem",
    "StoreConnector",
    "User",
    "utcnow",
]
