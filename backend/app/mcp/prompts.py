# SPDX-License-Identifier: GPL-3.0-or-later
"""MCP Prompts para Market Sano (Task 23, spec §9.3).

Tres prompts principales:
1. plan_week_within_budget - Planifica una semana de comidas
2. suggest_meals_from_pantry - Sugiere recetas con lo que hay en la despensa
3. compare_current_basket - Compara costos entre cadenas
"""

from app.mcp.server import mcp


@mcp.prompt()
def plan_week_within_budget(
    budget_str: str,
    free_nights_str: str = "1",
    variety_weeks_str: str = "4",
    store_id_str: str = "",
) -> str:
    """Plantilla para planificar una semana de comidas dentro del presupuesto.

    Usa esta plantilla para que el asistente genere un plan semanal
    optimizando precios y variedad.

    Args:
        budget_str: Presupuesto semanal en CLP (ej: "100000")
        free_nights_str: Número de noches libres (default: 1)
        variety_weeks_str: Semanas sin repetir recetas (default: 4)
        store_id_str: Cadena preferida (ej: "jumbo")
    """
    return f"""
Eres un planificador de comidas experto. Crea un plan semanal para este hogar
dentro del presupuesto indicado.

Presupuesto semanal: {budget_str} CLP
Noches libres: {free_nights_str}
Variedad: no repetir recetas de las últimas {variety_weeks_str} semanas
Cadena preferida: {store_id_str or 'usar la del hogar'}

Usa las siguientes tools:
1. get_household_context para ver configuración actual
2. suggest_meal_plan para generar el plan (dry_run=true primero)
3. create_meal_plan para guardar si el plan parece correcto

Instrucciones:
- Sugiere 7 cenas (descanso opcional en cena)
- Respetar presupuesto total
- Mantener variedad de recetas
- Confirmar plan con el usuario antes de crear

Devuelve el plan sugerido con estimado de costo total.
"""


@mcp.prompt()
def suggest_meals_from_pantry() -> str:
    """Plantilla para sugerir recetas con lo que hay en la despensa.

    Usa esta plantilla para que el asistente sugiera recetas que el usuario
    pueda cocinar con lo que ya tiene en su despensa.
    """
    return """
Eres un asistente de cocina. Analiza la despensa del usuario y sugiere
recetas que pueda preparar con los ingredientes disponibles.

Pasos:
1. Usa get_pantry_status para ver qué hay en la despensa
2. Usa search_recipes para encontrar recetas que coincidan
3. Sugerir 3-5 recetas con los ingredientes principales

Para cada receta sugerida:
- Mostrar ingredientes faltantes (si los hay)
- Estimar costo de compra para completar
- Preguntar si quiere que agregue a una lista de compras

Devuelve las sugerencias de recetas con notas sobre qué comprar.
"""


@mcp.prompt()
def compare_current_basket(list_id: str, threshold_str: str = "0.10") -> str:
    """Plantilla para comparar costos de una lista de compras entre cadenas.

    Usa esta plantilla para que el asistente compare precios entre
    diferentes supermercados chilenos (Jumbo, Santa Isabel, Unimarc).

    Args:
        list_id: ID de la lista de compras
        threshold_str: Umbral de ahorro para sugerir división (default: 0.10 = 10%)
    """
    return f"""
Eres un asistente de compras. Compara el costo de esta lista de compras
entre las diferentes cadenas de supermercados en Chile.

Lista de compras ID: {list_id}
Umbral de ahorro: {threshold_str} (10%)

Usa la tool compare_basket_across_stores para:
1. Calcular el costo total en cada cadena
2. Identificar productos donde una cadena es más barata
3. Sugerir si conviene dividir la compra

Devuelve:
- Costo total por cadena
- Productos más baratos por tienda
- Recomendación de división si ahorro > {threshold_str * 100}%
- Lista de sugerencias específicas por producto

Basado en PPUM (precio por unidad) para comparaciones justas.
"""