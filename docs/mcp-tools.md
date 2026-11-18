<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# API MCP de Market Sano

El backend expone su lógica como servidor MCP (spec §3.7): mismo código que la API REST, distinto entrypoint — `python -m app.mcp_server` (transporte **stdio**) para clientes locales como Claude Desktop o Cursor. El transporte HTTP (para agentes en red local) llega en la Task 23 del plan.

## Reglas de seguridad (spec §2.2)

- **Fase 0 — solo lectura:** las tres tools disponibles no escriben en la base.
- Con `AUTH_MODE=none` (por defecto) no se requiere autenticación: el invocador opera como owner implícito del hogar por defecto.
- Las tools de escritura (Fase 2 del plan) aceptarán `dry_run` (por defecto `true`); confirmar planes y registrar gastos exigirá un token emitido por un humano.

## Tools disponibles (Fase 0)

### `get_household_context`

Devuelve la configuración del hogar (spec §3.1).

| Parámetro | Tipo | Notas |
|---|---|---|
| `household_id` | int \| null | Omitir usa el hogar por defecto (modo single-user) |

**Retorno:** `{id, name, currency, timezone, weekly_budget_clp, default_store, dietary_restrictions, allergies, never_buy, comuna}`

```json
{
  "id": 1,
  "name": "Mi Hogar",
  "currency": "CLP",
  "timezone": "America/Santiago",
  "weekly_budget_clp": 45000,
  "default_store": "jumbo",
  "dietary_restrictions": [],
  "allergies": [],
  "never_buy": [],
  "comuna": null
}
```

**Errores accionables:** hogar inexistente (`household_id` inválido) o base sin datos (sugiere ejecutar `python -m app.seed`).

### `search_recipes`

Busca recetas por texto y etiquetas (spec §3.2). Versión Fase 0: los filtros `max_cost_per_serving`, `max_time_minutes` y `only_with_pantry_match` se agregan con la capa de costos (Task 11 del plan).

| Parámetro | Tipo | Notas |
|---|---|---|
| `query` | string | Busca en título **y descripción**, insensible a mayúsculas. Vacío: todas |
| `tags` | list[string] \| null | La receta debe tener **todas** las etiquetas (AND) |
| `max_results` | int | Por defecto 20 |

**Retorno:** lista de `{recipe_id, title, base_servings, time_minutes, difficulty, tags}`, ordenada alfabéticamente.

```json
[
  {
    "recipe_id": 1,
    "title": "Cazuela de vacuno",
    "base_servings": 4,
    "time_minutes": 80,
    "difficulty": "media",
    "tags": ["casera", "chilena", "guiso"]
  }
]
```

### `get_pantry_status`

Estado de la despensa (spec §3.3): cantidades por producto, ubicación e ítems próximos a vencer.

| Parámetro | Tipo | Notas |
|---|---|---|
| `household_id` | int \| null | Omitir usa el hogar por defecto |
| `location` | string \| null | `refrigerador`, `congelador`, `alacena`, `otro` |
| `expiring_within_days` | int \| null | Solo ítems que vencen en N días o menos |

**Retorno:** lista de `{product_id, product_name, quantity, unit, location, expires_at}` (ISO 8601 o null).

## Tools del catálogo abierto (Task 9b)

Requieren el conector de supermercados (`SUPERMERCADOS_ENABLED=true`, ver [docs/connectors](connectors/README.md)). Sin él, `search_store_products` responde con un error accionable.

### `search_store_products`

Busca directamente en una cadena. **Solo lectura.**

| Parámetro | Tipo | Notas |
|---|---|---|
| `query` | string | Ej. `"leche descremada"` |
| `store_id` | string | `jumbo` (defecto), `santaisabel`, `unimarc` |
| `limit` | int | 1–50, defecto 10 |

**Retorno:** lista de resultados del conector: `{name, brand, price, listPrice?, unitPrice, unit (kg\|lt\|un), url, sku, inStock, fetchedAt}`.

### `add_product_from_store`

Da de alta en el catálogo un resultado de `search_store_products`, o lo vincula a un producto existente, y fija su match por cadena para que el precio se actualice en vivo. **Escritura con `dry_run=true` por defecto:** muestra la vista previa al usuario y repite con `dry_run=false` solo si la confirma.

| Parámetro | Tipo | Notas |
|---|---|---|
| `store_id`, `store_url`, `store_product_name`, `unit`, `sku` | — | Copiados del resultado elegido (`url`, `name`, `unit`, `sku`) |
| `canonical_name` | string | Nombre en el catálogo; si ya existe (sin distinguir mayúsculas), se **vincula** |
| `category` | string | Defecto `otros` |
| `product_id` | int \| null | Vincular explícitamente a un producto existente |
| `dry_run` | bool | Defecto `true` |

**Retorno:** `{dry_run, accion: crear|vincular, match: crear|reemplazar, producto: {product_id, canonical_name, category, default_unit, purchase_unit, purchase_size}, store: {...}}`. La unidad canónica se infiere de `unit` (kg → g, lt → ml, un → unidad) y el pack, del nombre ("1 kg", "900 ml", "20 un").

**Errores accionables:** `unit` inválida; vincular un producto cuya unidad no es comparable (p. ej. `leche` en ml con un resultado por kg).

## Resource

| URI | Descripción |
|---|---|
| `household://{id}/context` | Configuración completa del hogar (mismo contenido que `get_household_context`) |

## Roadmap del contrato

| Fase del plan | Agregados |
|---|---|
| Task 11 | Filtros de costo/tiempo y `only_with_pantry_match` en `search_recipes` |
| Task 10+ | `create_recipe` (con `dry_run`), `rate_recipe`, `get_recipe`, `scale_recipe` |
| Task 14–22 | Planificación, listas, comparación de cadenas y gastos; tokens de confirmación |
| Task 23 | Transporte HTTP (streamable) + prompts `plan_week_within_budget`, `suggest_meals_from_pantry`, `compare_current_basket` |

## Verificación

Los tests (`backend/tests/test_mcp.py`) cubren el protocolo completo con el cliente in-memory de FastMCP **y** un roundtrip stdio real (`python -m app.mcp_server` como subproceso, igual que lo hace Claude Desktop) contra una base migrada y sembrada.
