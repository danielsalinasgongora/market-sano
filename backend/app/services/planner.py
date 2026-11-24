# SPDX-License-Identifier: GPL-3.0-or-later
"""Planificador semanal (Task 16, spec §3.4): plan draft, entradas por slot,
estimación de costo por cadena con snapshots y estado del presupuesto.

Reglas:
- Un plan por hogar y semana: `week_start` se normaliza al lunes de esa semana.
- Las entradas viven dentro de la semana del plan y son únicas por día+slot.
- El costo se valoriza con el último precio de cada ingrediente en la cadena
  (PriceService) y se multiplica por `servings_multiplier`.
- La "noche libre" (`recipe_id=None`) se contabiliza con `estimated_cost_clp`.
- Un plan `confirmed` o `archived` no admite cambios de entradas (T17).
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from app.models import (
    BudgetSnapshot,
    HouseholdPreference,
    MealPlan,
    MealPlanEntry,
    Recipe,
    StoreConnector,
)
from app.models.enums import MealSlot, PlanStatus
from app.services.recipes import NoEncontrada, costo_receta
from app.services.units import a_clp

SLOTS: tuple[MealSlot, ...] = (
    MealSlot.desayuno,
    MealSlot.almuerzo,
    MealSlot.cena,
    MealSlot.snack,
)
_SLOT_ORDEN = {slot: orden for orden, slot in enumerate(SLOTS)}


class PlanInvalido(ValueError):
    """Datos de plan inválidos (mensaje accionable)."""


class PlanNoEncontrado(LookupError):
    """El plan no existe o es de otro hogar."""


def normalizar_semana(dia: date) -> date:
    return dia - timedelta(days=dia.weekday())


def _slot(valor: str | MealSlot) -> MealSlot:
    try:
        return valor if isinstance(valor, MealSlot) else MealSlot(str(valor).strip().lower())
    except ValueError as exc:
        raise PlanInvalido(
            f"Slot inválido: {valor!r}. Usa {', '.join(s.value for s in SLOTS)}."
        ) from exc


def _plan_del_hogar(session: Session, plan_id: int, household_id: int) -> MealPlan:
    plan = session.get(MealPlan, plan_id)
    if plan is None or plan.household_id != household_id:
        raise PlanNoEncontrado(f"No existe el plan {plan_id} para tu hogar.")
    return plan


def _entrada_dict(session: Session, entrada: MealPlanEntry) -> dict[str, Any]:
    receta = session.get(Recipe, entrada.recipe_id) if entrada.recipe_id else None
    return {
        "entry_id": entrada.id,
        "date": entrada.date.isoformat(),
        "meal_slot": entrada.meal_slot.value,
        "recipe_id": entrada.recipe_id,
        "recipe_title": receta.title if receta else None,
        "label": entrada.label,
        "servings_multiplier": entrada.servings_multiplier,
        "estimated_cost_clp": entrada.estimated_cost_clp,
        "sort_order": entrada.sort_order,
    }


def _plan_dict(session: Session, plan: MealPlan) -> dict[str, Any]:
    entradas = session.exec(
        select(MealPlanEntry).where(MealPlanEntry.plan_id == plan.id)
    ).all()
    entradas.sort(key=lambda e: (e.date, _SLOT_ORDEN.get(e.meal_slot, 99), e.id or 0))
    return {
        "plan_id": plan.id,
        "household_id": plan.household_id,
        "week_start": plan.week_start.isoformat(),
        "week_end": (plan.week_start + timedelta(days=6)).isoformat(),
        "budget_clp": plan.budget_clp,
        "status": plan.status.value,
        "created_at": plan.created_at.isoformat(),
        "confirmed_at": plan.confirmed_at.isoformat() if plan.confirmed_at else None,
        "entries": [_entrada_dict(session, e) for e in entradas],
    }


def crear_plan(
    session: Session,
    household_id: int,
    *,
    week_start: date,
    budget_clp: int,
    created_by: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Crea el plan draft de la semana; falla si ya existe (uno por hogar+semana)."""
    lunes = normalizar_semana(week_start)
    if budget_clp <= 0:
        raise PlanInvalido("budget_clp debe ser mayor que 0.")
    existente = session.exec(
        select(MealPlan).where(
            MealPlan.household_id == household_id, MealPlan.week_start == lunes
        )
    ).first()
    if existente is not None:
        raise PlanInvalido(
            f"Ya existe el plan {existente.id} para la semana del {lunes.isoformat()}. "
            "Edítalo en vez de crear otro (un plan por hogar y semana)."
        )
    plan = MealPlan(
        household_id=household_id,
        week_start=lunes,
        budget_clp=budget_clp,
        created_by=created_by,
    )
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return _plan_dict(session, plan)


def obtener_plan(session: Session, household_id: int, plan_id: int) -> dict[str, Any]:
    return _plan_dict(session, _plan_del_hogar(session, plan_id, household_id))


def listar_planes(
    session: Session, household_id: int, *, week_start: date | None = None
) -> list[dict[str, Any]]:
    consulta = select(MealPlan).where(MealPlan.household_id == household_id)
    if week_start is not None:
        consulta = consulta.where(MealPlan.week_start == normalizar_semana(week_start))
    planes = session.exec(consulta.order_by(MealPlan.week_start.desc())).all()
    return [_plan_dict(session, plan) for plan in planes]


def _validar_receta(session: Session, recipe_id: int, household_id: int) -> Recipe:
    receta = session.get(Recipe, recipe_id)
    if receta is None:
        raise NoEncontrada(f"No existe la receta {recipe_id}.")
    if receta.household_id not in (None, household_id):
        raise PlanInvalido(
            f"La receta {recipe_id} es privada de otro hogar; usa una receta "
            "pública o propia."
        )
    return receta


def definir_entrada(
    session: Session,
    household_id: int,
    plan_id: int,
    *,
    fecha: date,
    meal_slot: str | MealSlot,
    recipe_id: int | None = None,
    servings_multiplier: float = 1.0,
    label: str | None = None,
    estimated_cost_clp: int | None = None,
) -> dict[str, Any]:
    """Crea o reemplaza la entrada del día+slot (upsert); devuelve el plan."""
    plan = _plan_del_hogar(session, plan_id, household_id)
    if plan.status is not PlanStatus.draft:
        raise PlanInvalido(
            f"El plan está {plan.status.value}: no admite cambios. Crea o usa un plan draft."
        )
    slot = _slot(meal_slot)
    fin = plan.week_start + timedelta(days=6)
    if not plan.week_start <= fecha <= fin:
        raise PlanInvalido(
            f"{fecha.isoformat()} está fuera de la semana del plan "
            f"({plan.week_start.isoformat()} a {fin.isoformat()})."
        )
    if servings_multiplier <= 0:
        raise PlanInvalido("servings_multiplier debe ser mayor que 0.")

    if recipe_id is not None:
        _validar_receta(session, recipe_id, household_id)
        if estimated_cost_clp is not None:
            raise PlanInvalido(
                "estimated_cost_clp solo aplica a la noche libre (sin receta)."
            )
        etiqueta = label.strip()[:120] if label and label.strip() else None
    else:
        if not label or not label.strip():
            raise PlanInvalido(
                "Sin receta debes indicar label (p. ej. 'Noche libre: sobras')."
            )
        if estimated_cost_clp is None or estimated_cost_clp < 0:
            raise PlanInvalido(
                "La noche libre requiere estimated_cost_clp >= 0 para descontar del presupuesto."
            )
        etiqueta = label.strip()[:120]

    entrada = session.exec(
        select(MealPlanEntry).where(
            MealPlanEntry.plan_id == plan.id,
            MealPlanEntry.date == fecha,
            MealPlanEntry.meal_slot == slot,
        )
    ).first()
    if entrada is None:
        entrada = MealPlanEntry(plan_id=plan.id, date=fecha, meal_slot=slot)
    entrada.recipe_id = recipe_id
    entrada.servings_multiplier = servings_multiplier
    entrada.label = etiqueta
    entrada.estimated_cost_clp = estimated_cost_clp
    entrada.sort_order = _SLOT_ORDEN[slot]
    session.add(entrada)
    session.commit()
    return _plan_dict(session, plan)


def eliminar_entrada(
    session: Session, household_id: int, plan_id: int, entry_id: int
) -> dict[str, Any]:
    """Quita una entrada del plan draft."""
    plan = _plan_del_hogar(session, plan_id, household_id)
    if plan.status is not PlanStatus.draft:
        raise PlanInvalido(f"El plan está {plan.status.value}: no admite cambios.")
    entrada = session.get(MealPlanEntry, entry_id)
    if entrada is None or entrada.plan_id != plan.id:
        raise PlanNoEncontrado(f"No existe la entrada {entry_id} en el plan {plan.id}.")
    session.delete(entrada)
    session.commit()
    return _plan_dict(session, plan)


def _cadenas_por_defecto(session: Session, household_id: int) -> list[str]:
    preferencia = session.get(HouseholdPreference, household_id)
    if preferencia and preferencia.default_store_id:
        return [preferencia.default_store_id]
    conector = session.exec(select(StoreConnector).order_by(StoreConnector.name)).first()
    return [conector.name if conector else "jumbo"]


def _costo_entradas(
    session: Session, plan: MealPlan, store_id: str
) -> tuple[int, bool, list[str], list[dict[str, Any]]]:
    """(total CLP, completo, faltantes, desglose) de las entradas del plan."""
    entradas = session.exec(
        select(MealPlanEntry).where(MealPlanEntry.plan_id == plan.id)
    ).all()
    entradas.sort(key=lambda e: (e.date, _SLOT_ORDEN.get(e.meal_slot, 99), e.id or 0))
    cache: dict[int, dict[str, Any]] = {}
    total, completo = 0, True
    faltantes: set[str] = set()
    lineas: list[dict[str, Any]] = []
    for entrada in entradas:
        if entrada.recipe_id is None:
            costo = entrada.estimated_cost_clp or 0
            lineas.append({
                "entry_id": entrada.id,
                "date": entrada.date.isoformat(),
                "meal_slot": entrada.meal_slot.value,
                "recipe_id": None,
                "title": entrada.label or "Noche libre",
                "servings_multiplier": entrada.servings_multiplier,
                "cost_clp": costo,
                "is_complete": True,
            })
            total += costo
            continue
        if entrada.recipe_id not in cache:
            cache[entrada.recipe_id] = costo_receta(session, entrada.recipe_id, store_id)
        detalle = cache[entrada.recipe_id]
        costo = a_clp(detalle["total_clp"] * entrada.servings_multiplier)
        if not detalle["is_complete"]:
            completo = False
            faltantes.update(detalle["missing_products"])
        lineas.append({
            "entry_id": entrada.id,
            "date": entrada.date.isoformat(),
            "meal_slot": entrada.meal_slot.value,
            "recipe_id": entrada.recipe_id,
            "title": detalle["title"],
            "servings_multiplier": entrada.servings_multiplier,
            "cost_clp": costo,
            "is_complete": detalle["is_complete"],
        })
        total += costo
    return total, completo, sorted(faltantes), lineas


def estimar_costo_plan(
    session: Session,
    household_id: int,
    plan_id: int,
    *,
    store_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Estima el costo del plan por cadena y persiste un `BudgetSnapshot` por cadena."""
    plan = _plan_del_hogar(session, plan_id, household_id)
    cadenas = [s.strip() for s in (store_ids or []) if s and s.strip()]
    cadenas = list(dict.fromkeys(cadenas)) or _cadenas_por_defecto(session, household_id)

    resultados: list[dict[str, Any]] = []
    for cadena in cadenas:
        total, completo, faltantes, lineas = _costo_entradas(session, plan, cadena)
        snapshot = BudgetSnapshot(
            plan_id=plan.id,
            store_id=cadena,
            total_clp=total,
            breakdown={
                "entries": lineas,
                "is_complete": completo,
                "missing_products": faltantes,
            },
        )
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)
        resultados.append({
            "store_id": cadena,
            "total_clp": total,
            "is_complete": completo,
            "missing_products": faltantes,
            "entries": lineas,
            "snapshot_id": snapshot.id,
            "fetched_at": snapshot.fetched_at.isoformat(),
        })
    return {
        "plan_id": plan.id,
        "week_start": plan.week_start.isoformat(),
        "budget_clp": plan.budget_clp,
        "stores": resultados,
    }


def estado_presupuesto(
    session: Session, household_id: int, plan_id: int, *, store_id: str | None = None
) -> dict[str, Any]:
    """`budget_clp`, `estimated_clp` y `variance_clp` con el último snapshot.

    Si no hay snapshot para la cadena, se calcula y persiste uno al vuelo.
    `variance_clp` = presupuesto − estimado (negativo = excedido).
    """
    plan = _plan_del_hogar(session, plan_id, household_id)
    cadena = (store_id or "").strip() or _cadenas_por_defecto(session, household_id)[0]
    snapshot = session.exec(
        select(BudgetSnapshot)
        .where(BudgetSnapshot.plan_id == plan.id, BudgetSnapshot.store_id == cadena)
        .order_by(BudgetSnapshot.fetched_at.desc(), BudgetSnapshot.id.desc())
    ).first()
    if snapshot is None:
        estimar_costo_plan(session, household_id, plan.id, store_ids=[cadena])
        snapshot = session.exec(
            select(BudgetSnapshot)
            .where(BudgetSnapshot.plan_id == plan.id, BudgetSnapshot.store_id == cadena)
            .order_by(BudgetSnapshot.fetched_at.desc(), BudgetSnapshot.id.desc())
        ).first()
    assert snapshot is not None  # lo acaba de persistir estimar_costo_plan

    estimado = snapshot.total_clp
    varianza = plan.budget_clp - estimado
    uso = round(estimado / plan.budget_clp * 100, 1) if plan.budget_clp else 0.0
    estado = "over" if varianza < 0 else ("near" if uso >= 90 else "ok")
    return {
        "plan_id": plan.id,
        "week_start": plan.week_start.isoformat(),
        "status": plan.status.value,
        "store_id": cadena,
        "budget_clp": plan.budget_clp,
        "estimated_clp": estimado,
        "variance_clp": varianza,
        "usage_pct": uso,
        "budget_status": estado,
        "is_complete": bool(snapshot.breakdown.get("is_complete", True)),
        "missing_products": snapshot.breakdown.get("missing_products", []),
        "snapshot_id": snapshot.id,
        "estimated_at": snapshot.fetched_at.isoformat(),
    }


FREE_NIGHT_LABEL = "Noche libre: sobras o comida para llevar"
FREE_NIGHT_COST_CLP = 3_000
VARIETY_WEEKS = 4


def _clp(monto: int) -> str:
    """CLP con separador de miles chileno ($45.000)."""
    return "$" + f"{monto:,}".replace(",", ".")


class PresupuestoInsuficiente(PlanInvalido):
    """El presupuesto no alcanza para el plan mínimo con variedad."""

    def __init__(self, mensaje: str, *, minimo_clp: int, presupuesto_clp: int) -> None:
        super().__init__(mensaje)
        self.minimo_clp = minimo_clp
        self.presupuesto_clp = presupuesto_clp


def _recetas_recientes(
    session: Session, household_id: int, lunes: date, variacion_semanas: int
) -> set[int]:
    """Recetas usadas en las `variacion_semanas` anteriores al lunes dado."""
    desde = lunes - timedelta(weeks=max(0, variacion_semanas))
    filas = session.exec(
        select(MealPlanEntry.recipe_id)
        .join(MealPlan, MealPlanEntry.plan_id == MealPlan.id)
        .where(
            MealPlan.household_id == household_id,
            MealPlan.week_start >= desde,
            MealPlan.week_start < lunes,
            MealPlanEntry.recipe_id.is_not(None),
        )
    ).all()
    return {recipe_id for recipe_id in filas if recipe_id is not None}


def _candidatas(
    session: Session,
    household_id: int,
    lunes: date,
    cadena: str,
    variacion_semanas: int,
) -> list[dict[str, Any]]:
    """Recetas visibles, sin precios incompletos y fuera de la ventana de variedad."""
    excluidas = _recetas_recientes(session, household_id, lunes, variacion_semanas)
    candidatas: list[dict[str, Any]] = []
    for receta in session.exec(select(Recipe).order_by(Recipe.id)).all():
        if receta.household_id not in (None, household_id):
            continue
        if receta.id in excluidas:
            continue
        detalle = costo_receta(session, receta.id, cadena)
        if not detalle["is_complete"] or detalle["total_clp"] <= 0:
            continue
        candidatas.append({
            "recipe_id": receta.id,
            "recipe_title": receta.title,
            "cost_clp": detalle["total_clp"],
        })
    candidatas.sort(key=lambda c: (c["cost_clp"], c["recipe_title"].lower()))
    return candidatas


def sugerir_plan(
    session: Session,
    household_id: int,
    *,
    week_start: date,
    budget_clp: int,
    store_id: str | None = None,
    variety_weeks: int = VARIETY_WEEKS,
    free_nights: int = 1,
    free_night_cost_clp: int = FREE_NIGHT_COST_CLP,
    dry_run: bool = True,
    created_by: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Arma un plan draft de 7 cenas dentro del presupuesto y con variedad.

    Elige las recetas más baratas con precio completo que no se hayan usado en
    las últimas `variety_weeks` semanas; las últimas `free_nights` cenas se
    reservan como noche libre con `free_night_cost_clp` explícito. Si el
    presupuesto no alcanza para el mínimo, lanza `PresupuestoInsuficiente` con
    `minimo_clp` y `presupuesto_clp`.
    """
    if budget_clp <= 0:
        raise PlanInvalido("budget_clp debe ser mayor que 0.")
    if not 0 <= free_nights <= 6:
        raise PlanInvalido("free_nights debe estar entre 0 y 6.")
    if free_night_cost_clp < 0:
        raise PlanInvalido("free_night_cost_clp no puede ser negativo.")
    if variety_weeks < 0:
        raise PlanInvalido("variety_weeks no puede ser negativo.")

    lunes = normalizar_semana(week_start)
    if session.exec(
        select(MealPlan).where(
            MealPlan.household_id == household_id, MealPlan.week_start == lunes
        )
    ).first():
        raise PlanInvalido(
            f"Ya existe un plan para la semana del {lunes.isoformat()}. "
            "Archívalo o edítalo antes de sugerir otro."
        )

    cadena = (store_id or "").strip() or _cadenas_por_defecto(session, household_id)[0]
    necesarias = 7 - free_nights
    candidatas = _candidatas(session, household_id, lunes, cadena, variety_weeks)
    if len(candidatas) < necesarias:
        raise PlanInvalido(
            f"La variedad de {variety_weeks} semanas deja {len(candidatas)} recetas "
            f"con precio completo en {cadena} y se necesitan {necesarias}. Agrega "
            "recetas, precios o reduce la ventana de variedad."
        )
    elegidas = candidatas[:necesarias]
    total = sum(c["cost_clp"] for c in elegidas) + free_nights * free_night_cost_clp
    if total > budget_clp:
        raise PresupuestoInsuficiente(
            f"El plan mínimo con variedad cuesta {_clp(total)} y el presupuesto es "
            f"{_clp(budget_clp)} (faltan {_clp(total - budget_clp)}). Sube el "
            "presupuesto, reduce las noches libres o registra precios más baratos.",
            minimo_clp=total,
            presupuesto_clp=budget_clp,
        )

    entradas: list[dict[str, Any]] = []
    indice = 0
    for dia in range(7):
        fecha = lunes + timedelta(days=dia)
        if dia >= 7 - free_nights:
            entradas.append({
                "date": fecha.isoformat(),
                "meal_slot": "cena",
                "recipe_id": None,
                "recipe_title": None,
                "label": FREE_NIGHT_LABEL,
                "estimated_cost_clp": free_night_cost_clp,
                "cost_clp": free_night_cost_clp,
            })
            continue
        receta = elegidas[indice]
        indice += 1
        entradas.append({
            "date": fecha.isoformat(),
            "meal_slot": "cena",
            "recipe_id": receta["recipe_id"],
            "recipe_title": receta["recipe_title"],
            "label": None,
            "estimated_cost_clp": None,
            "cost_clp": receta["cost_clp"],
        })

    resumen = {
        "dry_run": dry_run,
        "week_start": lunes.isoformat(),
        "week_end": (lunes + timedelta(days=6)).isoformat(),
        "budget_clp": budget_clp,
        "estimated_clp": total,
        "variance_clp": budget_clp - total,
        "store_id": cadena,
        "variety_weeks": variety_weeks,
        "free_nights": free_nights,
        "free_night_cost_clp": free_night_cost_clp,
        "entries": entradas,
    }
    if dry_run:
        return {"plan_id": None, **resumen}

    plan = MealPlan(
        household_id=household_id,
        week_start=lunes,
        budget_clp=budget_clp,
        created_by=created_by,
    )
    session.add(plan)
    session.flush()
    for entrada in entradas:
        session.add(
            MealPlanEntry(
                plan_id=plan.id,
                date=date.fromisoformat(entrada["date"]),
                meal_slot=MealSlot.cena,
                recipe_id=entrada["recipe_id"],
                label=entrada["label"],
                estimated_cost_clp=entrada["estimated_cost_clp"],
                sort_order=_SLOT_ORDEN[MealSlot.cena],
            )
        )
    session.commit()
    session.refresh(plan)
    return {"plan_id": plan.id, **resumen, "status": plan.status.value}


def confirmar_plan(
    session: Session, household_id: int, plan_id: int
) -> dict[str, Any]:
    """Confirma un plan draft: exige entradas, precios completos y estar dentro
    del presupuesto. Una vez confirmado queda congelado para ediciones."""
    plan = _plan_del_hogar(session, plan_id, household_id)
    if plan.status is PlanStatus.confirmed:
        raise PlanInvalido(
            f"El plan {plan.id} ya está confirmado (desde {plan.confirmed_at})."
        )
    if plan.status is not PlanStatus.draft:
        raise PlanInvalido(
            f"El plan está {plan.status.value}: solo un draft se puede confirmar."
        )
    if not session.exec(
        select(MealPlanEntry).where(MealPlanEntry.plan_id == plan.id)
    ).first():
        raise PlanInvalido("El plan no tiene comidas: agrega entradas antes de confirmarlo.")

    estado = estado_presupuesto(session, household_id, plan.id)
    if not estado["is_complete"]:
        faltantes = ", ".join(estado["missing_products"]) or "algunos ingredientes"
        raise PlanInvalido(
            f"No se puede confirmar sin precios completos en {estado['store_id']}: "
            f"faltan {faltantes}. Registra precios manuales o refresca el conector."
        )
    if estado["variance_clp"] < 0:
        raise PlanInvalido(
            f"El plan excede el presupuesto en {_clp(-estado['variance_clp'])} "
            f"({_clp(estado['estimated_clp'])} estimado vs "
            f"{_clp(estado['budget_clp'])}). Ajusta comidas o sube el presupuesto "
            "antes de confirmar."
        )

    plan.status = PlanStatus.confirmed
    plan.confirmed_at = datetime.now(UTC)
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return {**_plan_dict(session, plan), "budget": estado}
