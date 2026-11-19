# SPDX-License-Identifier: GPL-3.0-or-later
"""Escalado de cantidades y conversión a CLP (spec §3.2, Anexo A).

Reglas del Anexo A:
- Unidades discretas (`unidad`: huevo, pan, cebolla…): ceil al entero, no se
  parte una unidad.
- Peso/volumen (`g`, `ml`): un decimal.
- Dinero: redondeo half-up al peso entero (`round()` de Python usa banker's,
  que reparte 2.5 → 2 y no es lo que espera un usuario chileno).

El PPUM (`unit_price_clp`) se expresa por 1 kg cuando la unidad canónica es
`g`, por 1 L cuando es `ml` y por unidad cuando es `unidad` (convención de
PriceService y del conector, Task 7/9).
"""

import math
from decimal import ROUND_HALF_UP, Decimal

UNIDADES_DISCRETAS = frozenset({"unidad"})

# Etiqueta del PPUM según la unidad canónica del producto (spec §7.3).
UNIDAD_PPUM = {"g": "CLP/kg", "ml": "CLP/L", "unidad": "CLP/unidad"}


class UnidadInvalida(ValueError):
    """Cantidad o unidad que no se puede escalar/convertir."""


def escalar_cantidad(cantidad: float, unidad: str, factor: float) -> float | int:
    """Escala `cantidad` por `factor` y aplica el redondeo del Anexo A.

    Las unidades discretas vuelven como `int` (ceil); g/ml como `float` con
    un decimal.
    """
    if factor <= 0:
        raise UnidadInvalida("El factor de escalado debe ser positivo.")
    escalada = cantidad * factor
    if unidad in UNIDADES_DISCRETAS:
        # Tolerancia de 6 decimales: 3 * 1.0000000000000002 no debe dar 4.
        return math.ceil(round(escalada, 6))
    return round(escalada, 1)


def costo_en_clp(cantidad: float, unidad: str, unit_price_clp: int) -> float:
    """Costo (sin redondear) de `cantidad` en unidad canónica usando el PPUM."""
    if unidad in ("g", "ml"):
        return cantidad / 1000 * unit_price_clp
    return cantidad * unit_price_clp


def a_clp(valor: float) -> int:
    """Redondeo monetario half-up a peso entero."""
    return int(Decimal(str(valor)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
