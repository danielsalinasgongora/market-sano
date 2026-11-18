# SPDX-License-Identifier: GPL-3.0-or-later
"""Utilidades compartidas del modelo de datos.

Convención de timestamps: todos los `*_at` se guardan en UTC y **deben ser
datetimes con timezone** — SQLModel 0.0.50 mapea `datetime` a su tipo
`UTCDateTime`, que rechaza datetimes ingenuos. Usa siempre `utcnow()`.
"""

from datetime import UTC, datetime

from sqlalchemy import JSON, Column


def utcnow() -> datetime:
    """Marca de tiempo UTC actual."""
    return datetime.now(UTC)


def json_column(nullable: bool = False) -> Column:
    """Columna JSON explícita.

    SQLModel no mapea `list` a sa.JSON (solo `dict`), así que todos los
    campos JSON del modelo declaran su columna con esta helper: uniforme,
    portable (SQLite/Postgres) y con nulabilidad explícita.
    """
    return Column(JSON, nullable=nullable)
