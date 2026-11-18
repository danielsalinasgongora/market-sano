# SPDX-License-Identifier: GPL-3.0-or-later
"""Hogar, autenticación y tokens (spec §3.1 y Anexo B)."""

import uuid
from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.common import json_column, utcnow
from app.models.enums import Role


class User(SQLModel, table=True):
    """Usuario local. `password_hash` es nullable para futuras cuentas OIDC."""

    __tablename__ = "users"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(unique=True, index=True, max_length=320)
    password_hash: str | None = Field(default=None, max_length=255)
    display_name: str = Field(max_length=120)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Household(SQLModel, table=True):
    """Hogar: la unidad de presupuesto y datos."""

    __tablename__ = "households"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=120)
    currency: str = Field(default="CLP", max_length=8)
    timezone: str = Field(default="America/Santiago", max_length=64)
    default_weekly_budget_clp: int | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)


class HouseholdMember(SQLModel, table=True):
    """Pertenencia de un usuario a un hogar, con rol."""

    __tablename__ = "household_members"
    __table_args__ = (
        UniqueConstraint("household_id", "user_id", name="uq_household_members_pair"),
    )

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="households.id", index=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    role: Role = Field(default=Role.member)
    joined_at: datetime = Field(default_factory=utcnow)


class HouseholdPreference(SQLModel, table=True):
    """Preferencias del hogar: una fila por hogar (spec §3.1)."""

    __tablename__ = "household_preferences"

    household_id: int = Field(foreign_key="households.id", primary_key=True)
    default_store_id: str | None = Field(default=None, max_length=64)
    dietary_restrictions: list[str] = Field(default_factory=list, sa_column=json_column())
    allergies: list[str] = Field(default_factory=list, sa_column=json_column())
    never_buy: list[str] = Field(default_factory=list, sa_column=json_column())
    comuna: str | None = Field(default=None, max_length=120)


class Invitation(SQLModel, table=True):
    """Código de un solo uso (24 h) para unirse a un hogar."""

    __tablename__ = "invitations"

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="households.id", index=True)
    code: str = Field(unique=True, index=True, max_length=32)
    created_by: uuid.UUID | None = Field(default=None, foreign_key="users.id")
    expires_at: datetime
    used_at: datetime | None = Field(default=None)


class ApiToken(SQLModel, table=True):
    """Token de API de larga duración, almacenado hasheado (Anexo B)."""

    __tablename__ = "api_tokens"

    id: int | None = Field(default=None, primary_key=True)
    user_id: uuid.UUID | None = Field(default=None, foreign_key="users.id", index=True)
    name: str = Field(max_length=120)
    token_hash: str = Field(unique=True, index=True, max_length=255)
    scopes: list[str] = Field(default_factory=lambda: ["read"], sa_column=json_column())
    created_at: datetime = Field(default_factory=utcnow)
    last_used_at: datetime | None = Field(default=None)
