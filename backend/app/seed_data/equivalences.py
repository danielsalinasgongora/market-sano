# SPDX-License-Identifier: GPL-3.0-or-later
"""Tabla de equivalencias de cocina (spec, Anexo A).

Los ingredientes de las recetas se expresan en unidad canónica (g, ml,
unidad). Esta tabla permite convertir medidas caseras a canónicas cuando
el usuario escribe o importa recetas. Los pesos son aproximaciones
razonables de referencia; el servicio de conversión (Task 11 del plan)
consume estos datos.
"""

# Volumen de medidas caseras, en mililitros.
EQUIVALENCIAS_VOLUMEN_ML: dict[str, float] = {
    "pizca": 0.5,
    "cucharadita": 5.0,
    "cucharada": 15.0,
    "cuarto de taza": 60.0,
    "media taza": 120.0,
    "taza": 240.0,
    "vaso": 200.0,
}

# Peso aproximado de una taza de productos a granel, en gramos.
PESO_POR_TAZA_G: dict[str, float] = {
    "arroz": 200.0,
    "azúcar": 200.0,
    "garbanzos": 180.0,
    "harina": 140.0,
    "lentejas": 190.0,
    "porotos": 190.0,
    "sal": 280.0,
}

# Peso aproximado de una cucharada de productos a granel, en gramos.
PESO_POR_CUCHARADA_G: dict[str, float] = {
    "arroz": 12.0,
    "azúcar": 12.0,
    "harina": 8.0,
    "sal": 15.0,
}
