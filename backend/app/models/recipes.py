# SPDX-License-Identifier: GPL-3.0-or-later
"""Recetas: núcleo de datos (spec §3.2)."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.common import json_column, utcnow
from app.models.enums import Difficulty, ImportSourceType, ImportStatus


class Recipe(SQLModel, table=True):
    """Receta. `household_id` NULL = receta pública/comunitaria."""

    __tablename__ = "recipes"

    id: int | None = Field(default=None, primary_key=True)
    household_id: int | None = Field(default=None, foreign_key="households.id", index=True)
    title: str = Field(index=True, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    base_servings: int = Field(default=4)
    prep_minutes: int | None = Field(default=None)
    cook_minutes: int | None = Field(default=None)
    difficulty: Difficulty | None = Field(default=None)
    instructions: str | None = Field(default=None)  # Markdown
    source_url: str | None = Field(default=None, max_length=2000)
    created_by: uuid.UUID | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class RecipeIngredient(SQLModel, table=True):
    """Ingrediente estructurado: siempre resuelve a un producto del catálogo."""

    __tablename__ = "recipe_ingredients"

    id: int | None = Field(default=None, primary_key=True)
    recipe_id: int = Field(foreign_key="recipes.id", index=True)
    product_id: int = Field(foreign_key="product_catalog.id", index=True)
    quantity: float
    unit: str = Field(max_length=32)
    optional: bool = Field(default=False)
    notes: str | None = Field(default=None, max_length=500)
    sort_order: int = Field(default=0)


class RecipeStep(SQLModel, table=True):
    """Paso ordenado de una receta."""

    __tablename__ = "recipe_steps"
    __table_args__ = (UniqueConstraint("recipe_id", "step_number", name="uq_recipe_steps_number"),)

    id: int | None = Field(default=None, primary_key=True)
    recipe_id: int = Field(foreign_key="recipes.id", index=True)
    step_number: int
    instruction: str
    duration_minutes: int | None = Field(default=None)


class RecipeTag(SQLModel, table=True):
    """Etiqueta de receta. PK compuesta (spec §3.2)."""

    __tablename__ = "recipe_tags"
    __table_args__ = (Index("ix_recipe_tags_tag", "tag"),)

    recipe_id: int = Field(foreign_key="recipes.id", primary_key=True)
    tag: str = Field(primary_key=True, max_length=100)


class RecipeRating(SQLModel, table=True):
    """Calificación 1-5 de un usuario sobre una receta (aprendizaje de gustos)."""

    __tablename__ = "recipe_ratings"
    __table_args__ = (
        UniqueConstraint("recipe_id", "user_id", name="uq_recipe_ratings_pair"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_recipe_ratings_range"),
    )

    id: int | None = Field(default=None, primary_key=True)
    recipe_id: int = Field(foreign_key="recipes.id", index=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    rating: int
    rated_at: datetime = Field(default_factory=utcnow)


class RecipeCollection(SQLModel, table=True):
    """Colección de recetas de un hogar."""

    __tablename__ = "recipe_collections"

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="households.id", index=True)
    name: str = Field(max_length=120)


class RecipeCollectionItem(SQLModel, table=True):
    """Pertenencia de una receta a una colección. PK compuesta."""

    __tablename__ = "recipe_collection_items"

    collection_id: int = Field(foreign_key="recipe_collections.id", primary_key=True)
    recipe_id: int = Field(foreign_key="recipes.id", primary_key=True)


class RecipeImportJob(SQLModel, table=True):
    """Job de importación de receta (URL, texto pegado o video)."""

    __tablename__ = "recipe_import_jobs"

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="households.id", index=True)
    source_type: ImportSourceType
    source_value: str
    status: ImportStatus = Field(default=ImportStatus.pending)
    result_json: dict | None = Field(default=None, sa_column=json_column(nullable=True))
    error_message: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = Field(default=None)
