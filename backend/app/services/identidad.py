# SPDX-License-Identifier: GPL-3.0-or-later
"""Identidad con `AUTH_MODE=none`: hogar por defecto y su owner implícito.

Sin login, toda escritura que necesita un usuario (calificaciones, autoría)
se atribuye a un usuario local creado bajo demanda. T13 reemplaza esto por el
usuario autenticado cuando `AUTH_MODE=local`.
"""

from sqlmodel import Session, select

from app.models import Household, HouseholdMember, User
from app.models.enums import Role

EMAIL_LOCAL = "owner@marketsano.local"


class SinHogar(LookupError):
    """La base no tiene hogares (mensaje accionable)."""


def hogar_por_defecto(session: Session) -> Household:
    hogar = session.exec(select(Household).order_by(Household.id).limit(1)).first()
    if hogar is None:
        raise SinHogar(
            "La base no tiene hogares. Ejecuta `python -m app.seed` para crear el hogar "
            "por defecto."
        )
    return hogar


def owner_implicito(session: Session) -> tuple[Household, User]:
    """(hogar por defecto, su owner local), creando el usuario si falta."""
    hogar = hogar_por_defecto(session)
    usuario = session.exec(select(User).where(User.email == EMAIL_LOCAL)).first()
    if usuario is None:
        usuario = User(email=EMAIL_LOCAL, display_name="Owner local")
        session.add(usuario)
        session.flush()  # sin relationships, el orden de INSERT no se infiere
        session.add(HouseholdMember(household_id=hogar.id, user_id=usuario.id, role=Role.owner))
        session.commit()
    return hogar, usuario
