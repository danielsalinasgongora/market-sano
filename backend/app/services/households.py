# SPDX-License-Identifier: GPL-3.0-or-later
"""Hogares, miembros, roles, invitaciones y supresión (spec §3.1, Task 14).

Reglas:
- `owner`: todo, incluido borrar el hogar.
- `member`: escribe recetas y preferencias, invita y borra sus propios datos.
- `viewer`: solo lectura.
- Invitación: código alfanumérico de un solo uso, válido 24 h.

El borrado de un hogar elimina explícitamente sus datos dependientes (el
esquema no usa `ON DELETE CASCADE` para hogares) y conserva catálogo, precios
y recetas públicas/comunitarias.
"""

import secrets
import string
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, or_
from sqlmodel import Session, func, select

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
from app.models.enums import Role

ROLES_ESCRITURA = frozenset({Role.owner, Role.member})
_CAMPOS_PREFERENCIA = {
    "default_store_id": 64,
    "dietary_restrictions": None,
    "allergies": None,
    "never_buy": None,
    "comuna": 120,
}
_ALFABETO_CODIGO = string.ascii_uppercase + string.digits
_TTL_INVITACION_HORAS = 24


class HogarNoEncontrado(LookupError):
    """El hogar no existe o el usuario no pertenece a él."""


class SinPermiso(PermissionError):
    """El rol del usuario no permite la operación."""


class InvitacionInvalida(ValueError):
    """Código inválido, expirado o ya utilizado."""


class SolicitudInvalida(ValueError):
    """Datos de hogar o preferencias inválidos."""


@dataclass
class ContextoHogar:
    """Hogar y rol con los que opera la request."""

    hogar: Household
    usuario: User
    rol: Role


def membresia(
    session: Session, user_id: Any, household_id: int
) -> HouseholdMember | None:
    return session.exec(
        select(HouseholdMember).where(
            HouseholdMember.user_id == user_id,
            HouseholdMember.household_id == household_id,
        )
    ).first()


def rol_en(session: Session, user: User, household_id: int) -> Role | None:
    fila = membresia(session, user.id, household_id)
    return fila.role if fila else None


def _exigir_hogar(session: Session, household_id: int) -> Household:
    hogar = session.get(Household, household_id)
    if hogar is None:
        raise HogarNoEncontrado(f"No existe el hogar {household_id}.")
    return hogar


def exigir_rol(
    session: Session, user: User, household_id: int, roles: set[Role] | frozenset[Role]
) -> Household:
    """Valida pertenencia y rol; 404 si no es miembro, 403 si el rol no alcanza."""
    hogar = _exigir_hogar(session, household_id)
    rol = rol_en(session, user, household_id)
    if rol is None:
        # No revelar si el hogar existe: para este usuario, no existe.
        raise HogarNoEncontrado(f"No existe el hogar {household_id}.")
    if rol not in roles:
        permitidos = ", ".join(sorted(r.value for r in roles))
        raise SinPermiso(
            f"Tu rol '{rol.value}' no permite esta operación; requiere {permitidos}."
        )
    return hogar


def exigir_escritura(session: Session, user: User, household_id: int) -> Household:
    return exigir_rol(session, user, household_id, ROLES_ESCRITURA)


def contexto_usuario(
    session: Session, user: User, household_id: int | None = None
) -> ContextoHogar:
    """Hogar activo del usuario: el pedido (validando membresía) o el primero."""
    if household_id is not None:
        hogar = exigir_rol(session, user, household_id, frozenset(Role))
        return ContextoHogar(hogar, user, rol_en(session, user, household_id) or Role.viewer)
    fila = session.exec(
        select(HouseholdMember)
        .where(HouseholdMember.user_id == user.id)
        .order_by(HouseholdMember.joined_at, HouseholdMember.id)
    ).first()
    if fila is None:
        raise HogarNoEncontrado(
            "Tu usuario no pertenece a ningún hogar. Crea uno o únete con un código "
            "de invitación."
        )
    hogar = _exigir_hogar(session, fila.household_id)
    return ContextoHogar(hogar, user, fila.role)


def listar_hogares(session: Session, user: User) -> list[dict[str, Any]]:
    filas = session.exec(
        select(HouseholdMember)
        .where(HouseholdMember.user_id == user.id)
        .order_by(HouseholdMember.joined_at, HouseholdMember.id)
    ).all()
    resultado = []
    for fila in filas:
        hogar = session.get(Household, fila.household_id)
        if hogar is None:
            continue
        miembros = session.exec(
            select(func.count()).select_from(HouseholdMember).where(
                HouseholdMember.household_id == hogar.id
            )
        ).one()
        resultado.append({
            "household_id": hogar.id,
            "name": hogar.name,
            "role": fila.role.value,
            "member_count": miembros,
        })
    return resultado


def crear_hogar(session: Session, user: User, nombre: str) -> dict[str, Any]:
    limpio = (nombre or "").strip()
    if not limpio:
        raise SolicitudInvalida("Indica un nombre para el hogar.")
    hogar = Household(name=limpio[:120])
    session.add(hogar)
    session.flush()
    session.add(HouseholdMember(household_id=hogar.id, user_id=user.id, role=Role.owner))
    session.commit()
    session.refresh(hogar)
    return {
        "household_id": hogar.id,
        "name": hogar.name,
        "currency": hogar.currency,
        "timezone": hogar.timezone,
        "role": Role.owner.value,
    }


def miembros(session: Session, user: User, household_id: int) -> list[dict[str, Any]]:
    exigir_rol(session, user, household_id, frozenset(Role))
    filas = session.exec(
        select(HouseholdMember, User)
        .where(HouseholdMember.household_id == household_id)
        .join(User, User.id == HouseholdMember.user_id)
        .order_by(HouseholdMember.joined_at, HouseholdMember.id)
    ).all()
    return [
        {
            "user_id": str(usuario.id),
            "email": usuario.email,
            "display_name": usuario.display_name,
            "role": fila.role.value,
            "joined_at": fila.joined_at.isoformat(),
        }
        for fila, usuario in filas
    ]


def _codigo_unico(session: Session) -> str:
    for _ in range(20):
        codigo = "".join(secrets.choice(_ALFABETO_CODIGO) for _ in range(10))
        if session.exec(select(Invitation).where(Invitation.code == codigo)).first() is None:
            return codigo
    raise SolicitudInvalida("No se pudo generar un código de invitación; intenta de nuevo.")


def crear_invitacion(
    session: Session, user: User, household_id: int, ttl_hours: int = _TTL_INVITACION_HORAS
) -> dict[str, Any]:
    exigir_escritura(session, user, household_id)
    if ttl_hours < 1 or ttl_hours > 168:
        raise SolicitudInvalida("La invitación debe durar entre 1 y 168 horas.")
    invitacion = Invitation(
        household_id=household_id,
        code=_codigo_unico(session),
        created_by=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
    )
    session.add(invitacion)
    session.commit()
    session.refresh(invitacion)
    return {
        "code": invitacion.code,
        "household_id": household_id,
        "expires_at": invitacion.expires_at.isoformat(),
        "single_use": True,
    }


def unirse_con_codigo(session: Session, user: User, codigo: str) -> dict[str, Any]:
    limpio = (codigo or "").strip().upper()
    if not limpio:
        raise InvitacionInvalida("Ingresa el código de invitación.")
    invitacion = session.exec(
        select(Invitation).where(Invitation.code == limpio)
    ).first()
    if invitacion is None:
        raise InvitacionInvalida("Código de invitación inválido.")
    if invitacion.used_at is not None:
        raise InvitacionInvalida(
            "Ese código ya fue utilizado; pide una invitación nueva."
        )
    if invitacion.expires_at < datetime.now(UTC):
        raise InvitacionInvalida(
            "El código de invitación expiró; pide uno nuevo al hogar."
        )
    if membresia(session, user.id, invitacion.household_id) is not None:
        raise InvitacionInvalida("Ya perteneces a ese hogar.")

    hogar = _exigir_hogar(session, invitacion.household_id)
    session.add(
        HouseholdMember(household_id=hogar.id, user_id=user.id, role=Role.member)
    )
    invitacion.used_at = datetime.now(UTC)
    session.add(invitacion)
    session.commit()
    return {
        "household_id": hogar.id,
        "name": hogar.name,
        "role": Role.member.value,
    }


def preferencias(
    session: Session, user: User, household_id: int
) -> dict[str, Any]:
    exigir_rol(session, user, household_id, frozenset(Role))
    fila = session.get(HouseholdPreference, household_id)
    return {
        "household_id": household_id,
        "default_store_id": fila.default_store_id if fila else None,
        "dietary_restrictions": list(fila.dietary_restrictions) if fila else [],
        "allergies": list(fila.allergies) if fila else [],
        "never_buy": list(fila.never_buy) if fila else [],
        "comuna": fila.comuna if fila else None,
    }


def _validar_cambios(cambios: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(cambios, dict) or not cambios:
        raise SolicitudInvalida("Envía al menos una preferencia para actualizar.")
    desconocidos = set(cambios) - set(_CAMPOS_PREFERENCIA)
    if desconocidos:
        raise SolicitudInvalida(
            f"Preferencias desconocidas: {', '.join(sorted(desconocidos))}. "
            f"Permitidas: {', '.join(_CAMPOS_PREFERENCIA)}."
        )
    limpios: dict[str, Any] = {}
    for campo, valor in cambios.items():
        limite = _CAMPOS_PREFERENCIA[campo]
        if limite is None:
            if valor is None:
                limpios[campo] = []
            elif not isinstance(valor, (list, tuple)) or not all(
                isinstance(x, str) for x in valor
            ):
                raise SolicitudInvalida(f"'{campo}' debe ser una lista de textos.")
            else:
                limpios[campo] = [x.strip().lower() for x in valor if x.strip()]
        else:
            if valor is not None and (not isinstance(valor, str) or len(valor) > limite):
                raise SolicitudInvalida(
                    f"'{campo}' debe ser texto de hasta {limite} caracteres o null."
                )
            limpios[campo] = valor.strip() if isinstance(valor, str) else None
    return limpios


def actualizar_preferencias(
    session: Session, user: User, household_id: int, cambios: dict[str, Any]
) -> dict[str, Any]:
    exigir_escritura(session, user, household_id)
    limpios = _validar_cambios(cambios)
    fila = session.get(HouseholdPreference, household_id)
    if fila is None:
        fila = HouseholdPreference(household_id=household_id)
    for campo, valor in limpios.items():
        setattr(fila, campo, valor)
    session.add(fila)
    session.commit()
    return preferencias(session, user, household_id)


def _ids(session: Session, consulta: Any) -> list[int]:
    return [fila for fila in session.exec(consulta).all() if fila is not None]


def eliminar_hogar(session: Session, user: User, household_id: int) -> None:
    """Borra el hogar y todos sus datos dependientes (solo owner)."""
    hogar = exigir_rol(session, user, household_id, {Role.owner})

    recetas = _ids(session, select(Recipe.id).where(Recipe.household_id == household_id))
    planes = _ids(session, select(MealPlan.id).where(MealPlan.household_id == household_id))
    listas = _ids(
        session, select(ShoppingList.id).where(ShoppingList.household_id == household_id)
    )
    despensa = _ids(
        session, select(PantryItem.id).where(PantryItem.household_id == household_id)
    )
    gastos = _ids(session, select(Expense.id).where(Expense.household_id == household_id))
    colecciones = _ids(
        session,
        select(RecipeCollection.id).where(RecipeCollection.household_id == household_id),
    )

    session.exec(delete(RecipeCollectionItem).where(
        or_(
            RecipeCollectionItem.recipe_id.in_(recetas),
            RecipeCollectionItem.collection_id.in_(colecciones),
        )
    ))
    session.exec(delete(RecipeIngredient).where(RecipeIngredient.recipe_id.in_(recetas)))
    session.exec(delete(RecipeStep).where(RecipeStep.recipe_id.in_(recetas)))
    session.exec(delete(RecipeTag).where(RecipeTag.recipe_id.in_(recetas)))
    session.exec(delete(RecipeRating).where(RecipeRating.recipe_id.in_(recetas)))

    # Las listas referencian planes (`plan_id`), así que salen antes que ellos.
    session.exec(delete(ShoppingListItem).where(ShoppingListItem.list_id.in_(listas)))
    session.exec(delete(ShoppingList).where(ShoppingList.household_id == household_id))

    session.exec(delete(MealPlanEntry).where(
        or_(
            MealPlanEntry.plan_id.in_(planes),
            MealPlanEntry.recipe_id.in_(recetas),
        )
    ))
    session.exec(delete(BudgetSnapshot).where(BudgetSnapshot.plan_id.in_(planes)))
    session.exec(delete(MealPlan).where(MealPlan.household_id == household_id))

    session.exec(delete(PantryMovement).where(
        PantryMovement.pantry_item_id.in_(despensa)
    ))
    session.exec(delete(PantryItem).where(PantryItem.household_id == household_id))

    session.exec(delete(ExpenseItem).where(ExpenseItem.expense_id.in_(gastos)))
    session.exec(delete(Expense).where(Expense.household_id == household_id))

    session.exec(delete(RecipeImportJob).where(RecipeImportJob.household_id == household_id))
    session.exec(delete(Invitation).where(Invitation.household_id == household_id))
    session.exec(delete(HouseholdPreference).where(
        HouseholdPreference.household_id == household_id
    ))
    session.exec(delete(RecipeCollection).where(
        RecipeCollection.household_id == household_id
    ))
    session.exec(delete(Recipe).where(Recipe.household_id == household_id))
    session.exec(delete(HouseholdMember).where(
        HouseholdMember.household_id == household_id
    ))
    session.delete(hogar)
    session.commit()
