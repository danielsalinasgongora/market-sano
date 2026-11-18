# SPDX-License-Identifier: GPL-3.0-or-later
"""Enumeraciones del dominio.

Convención: los miembros se definen en minúsculas con nombre == valor, para
que `sa.Enum` persista exactamente esos valores limpios en la base de datos
(SQLAlchemy guarda el *nombre* del miembro por defecto).
"""

import enum


class Role(enum.StrEnum):
    """Roles de un miembro dentro de un hogar (spec §3.1)."""

    owner = "owner"
    member = "member"
    viewer = "viewer"


class PlanStatus(enum.StrEnum):
    """Estado de un plan semanal (spec §3.4)."""

    draft = "draft"
    confirmed = "confirmed"
    archived = "archived"


class ListStatus(enum.StrEnum):
    """Estado de una lista de compras."""

    active = "active"
    completed = "completed"


class MealSlot(enum.StrEnum):
    """Comidas del día (spec §3.4)."""

    desayuno = "desayuno"
    almuerzo = "almuerzo"
    cena = "cena"
    snack = "snack"


class PriceSource(enum.StrEnum):
    """Origen de un precio (trazabilidad, spec §0.6)."""

    live = "live"
    cached = "cached"
    manual = "manual"


class PriceConfidence(enum.StrEnum):
    """Nivel de confianza de un precio (spec §0.6)."""

    high = "high"
    medium = "medium"
    low = "low"


class PantryLocation(enum.StrEnum):
    """Ubicación física de un ítem de despensa (spec §3.3)."""

    refrigerador = "refrigerador"
    congelador = "congelador"
    alacena = "alacena"
    otro = "otro"


class MovementReason(enum.StrEnum):
    """Motivo de un movimiento de despensa (spec §3.3)."""

    purchase = "purchase"
    recipe_consumption = "recipe_consumption"
    manual_adjustment = "manual_adjustment"
    spoilage = "spoilage"


class Difficulty(enum.StrEnum):
    """Dificultad de una receta."""

    facil = "facil"
    media = "media"
    dificil = "dificil"


class ImportSourceType(enum.StrEnum):
    """Fuente de importación de recetas (spec §3.2)."""

    url = "url"
    text = "text"
    video = "video"


class ImportStatus(enum.StrEnum):
    """Estado de un job de importación."""

    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"
