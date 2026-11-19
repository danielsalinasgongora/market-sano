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

Busca recetas con filtros combinables (spec §3.2, Task 11). `only_with_pantry_match` se agrega en Task 19.

| Parámetro | Tipo | Notas |
|---|---|---|
| `query` | string | Busca en título **y descripción**, insensible a mayúsculas. Vacío: todas |
| `tags` | list[string] \| null | La receta debe tener **todas** las etiquetas (AND) |
| `max_cost_per_serving` | float \| null | Costo máximo por porción en CLP. Excluye recetas con precios incompletos (un costo parcial no es comparable) |
| `max_time_minutes` | int \| null | Tiempo total máximo: `prep_minutes + cook_minutes` |
| `store_id` | string \| null | Cadena para los costos (`jumbo`, `santaisabel`, `unimarc`). Omitir usa la cadena por defecto del hogar |
| `sort` | string | `title` (defecto), `cost` (ascendente; sin precio al final) o `rating` (descendente) |
| `max_results` | int | Por defecto 20 |

**Retorno:** lista de `{recipe_id, title, base_servings, time_minutes, difficulty, tags, own, avg_rating, rating_count, cost_per_serving_clp, is_complete_cost}`, ordenada según `sort`. El costo usa el último precio de cada ingrediente y su PPUM; `cost_per_serving_clp` es `null` cuando falta el precio de algún ingrediente.

```json
[
  {
    "recipe_id": 1,
    "title": "Cazuela de vacuno",
    "base_servings": 4,
    "time_minutes": 80,
    "difficulty": "media",
    "tags": ["casera", "chilena", "guiso"],
    "own": false,
    "avg_rating": 4.5,
    "rating_count": 2,
    "cost_per_serving_clp": 2948,
    "is_complete_cost": true
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

## Tools de recetas (Task 10–12)

Con `AUTH_MODE=none` el invocador actúa como owner implícito del hogar por defecto. Los permisos por rol y token llegan en T15.

### `get_recipe`

`recipe_id` → `{recipe_id, household_id, title, description, base_servings, prep_minutes, cook_minutes, difficulty, instructions (Markdown), ingredients[{product_id, product_name, quantity, unit, optional, notes}], steps[{step_number, instruction, duration_minutes}], tags, rating_avg, rating_count}`.

### `create_recipe`

Crea una receta propia del hogar. **Escritura con `dry_run=true` por defecto.**

| Parámetro | Tipo | Notas |
|---|---|---|
| `title` | string | |
| `ingredients` | list | `{product, quantity, unit, optional?, notes?}`. `product` es un nombre/alias del catálogo o un `product_id`; `unit` es la del catálogo (`g`, `ml`, `unidad`) o una convertible (`kg`, `L`, `cc`) |
| `steps` | list \| null | `{instruction, duration_minutes?}` en orden |
| `base_servings`, `prep_minutes`, `cook_minutes`, `difficulty`, `description`, `instructions`, `tags` | — | Opcionales; `difficulty`: `facil`, `media` o `dificil` |
| `dry_run` | bool | Defecto `true`: valida y devuelve la vista previa sin guardar |

**Errores accionables:** si un ingrediente no está en el catálogo, sugiere nombres parecidos y `add_product_from_store`; también hay error si la unidad es incompatible con la del producto. Las recetas de la semilla son de solo lectura (la edición es por API, `PUT /api/v1/recipes/{id}`, solo para recetas propias).

### `import_recipe`

Importa una receta desde una URL que publique datos estructurados JSON-LD (`schema.org/Recipe`). **Escritura con `dry_run=true` por defecto.** También disponible por REST: `POST /api/v1/recipes/imports?dry_run=true|false`.

| Parámetro | Tipo | Notas |
|---|---|---|
| `url` | string | `http://` o `https://`; debe apuntar a una receta con JSON-LD |
| `dry_run` | bool | Defecto `true`: devuelve la vista previa sin guardar |

**Pipeline:** descarga el HTML (20 s de timeout, 5 MB máximo) → extrae título, porciones, tiempos, etiquetas y pasos con `recipe-scrapers` → mapea cada ingrediente al catálogo por nombre/alias (tolera plurales y variantes como "aceite de girasol" → `aceite`) → convierte medidas caseras (`kg`, `cucharada`, `taza`, …) a la unidad canónica con el Anexo A.

**Retorno:** `{dry_run, job_id, recipe_id, title, description, base_servings, prep_minutes, cook_minutes, instructions, steps[], tags[], source_url, ingredients[{product_id, product_name, quantity, unit, raw_text}], unresolved[{text, reason, suggestions[]}], is_complete, warning?}`.

- Los ingredientes que no se pueden mapear o convertir **no se pierden ni se inventan**: vuelven en `unresolved` con el motivo y sugerencias del catálogo, y la receta se crea solo con los resueltos (`is_complete=false`, `warning` accionable).
- Con `dry_run=false` **siempre** queda un `recipe_import_job`: `completed` con `result_json`, o `failed` con `error_message` (URL inválida, página sin JSON-LD, sin ingredientes mapeables). Con `dry_run=true` no se persiste nada.

```json
{
  "dry_run": false,
  "job_id": 7,
  "recipe_id": 21,
  "title": "Lentejas a la jardinera",
  "base_servings": 4,
  "ingredients": [
    {"product_id": 31, "product_name": "lentejas", "quantity": 300.0,
     "unit": "g", "raw_text": "300 gramos de Lentejas"}
  ],
  "unresolved": [
    {"text": "2 ramas de Tomillo", "reason": "'Tomillo' no está en el catálogo",
     "suggestions": []}
  ],
  "is_complete": false,
  "warning": "1 ingrediente(s) no se pudieron estructurar (2 ramas de Tomillo); quedaron en el job para revisarlos con add_product_from_store."
}
```

**Errores accionables:** URL inválida o no descargable; la página no expone JSON-LD; ningún ingrediente se pudo estructurar (sugiere agregar productos con `add_product_from_store` o importar con texto pegado).

### `rate_recipe`

`recipe_id`, `rating` (1–5) → `{recipe_id, your_rating, rating_avg, rating_count}`. Una calificación por usuario; repetir la reemplaza.

### `scale_recipe`

Escala los ingredientes a `target_servings` con las reglas del Anexo A: unidades discretas (`unidad`) → **ceil** al entero; peso/volumen (`g`, `ml`) → un decimal. **Solo lectura.**

| Parámetro | Tipo | Notas |
|---|---|---|
| `recipe_id` | int | |
| `target_servings` | int | 1 o más |

**Retorno:** `{recipe_id, title, base_servings, target_servings, factor, ingredients[{product_id, product_name, quantity, original_quantity, unit, optional, notes}]}`.

```json
{
  "recipe_id": 3,
  "title": "Empanadas de pino",
  "base_servings": 12,
  "target_servings": 5,
  "factor": 0.4167,
  "ingredients": [
    {"product_id": 44, "product_name": "huevo", "quantity": 2,
     "original_quantity": 3, "unit": "unidad", "optional": false, "notes": null}
  ]
}
```

### `get_recipe_cost`

Costo de una receta con el último precio de cada ingrediente en una cadena (spec §3.2). **Solo lectura.**

| Parámetro | Tipo | Notas |
|---|---|---|
| `recipe_id` | int | |
| `store_id` | string \| null | `jumbo`, `santaisabel` o `unimarc`; omitir usa la cadena del hogar |

**Retorno:** `{recipe_id, title, store_id, base_servings, total_clp, cost_per_serving_clp, is_complete, missing_products, ingredients[{product_id, product_name, quantity, unit, optional, ppum_unit, cost_clp, unit_price_clp, price}]}`. `price` trae la trazabilidad completa (`source`, `source_efectiva`, `confidence`, `confidence_efectiva`, `fetched_at`, `is_stale`, `age_hours`).

Si falta el precio de algún ingrediente, `is_complete=false`, `missing_products` lista los nombres y `warning` explica cómo refrescar; el total cubre solo lo valorizado. El costo se calcula con el **PPUM**: `g → CLP/kg`, `ml → CLP/L`, `unidad → CLP/unidad`.

```json
{
  "recipe_id": 1,
  "title": "Cazuela de vacuno",
  "store_id": "jumbo",
  "base_servings": 4,
  "total_clp": 11792,
  "cost_per_serving_clp": 2948,
  "is_complete": true,
  "missing_products": [],
  "ingredients": [
    {
      "product_id": 12, "product_name": "papa", "quantity": 800.0, "unit": "g",
      "optional": false, "ppum_unit": "CLP/kg", "cost_clp": 1144,
      "unit_price_clp": 1430, "price": {"source": "live", "confidence": "high", "is_stale": false}
    }
  ]
}
```

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
| Task 19 | `only_with_pantry_match` en `search_recipes` |
| Task 14–22 | Planificación, listas, comparación de cadenas y gastos; tokens de confirmación |
| Task 23 | Transporte HTTP (streamable) + prompts `plan_week_within_budget`, `suggest_meals_from_pantry`, `compare_current_basket` |

## Verificación

Los tests (`backend/tests/test_mcp.py`) cubren el protocolo completo con el cliente in-memory de FastMCP **y** un roundtrip stdio real (`python -m app.mcp_server` como subproceso, igual que lo hace Claude Desktop) contra una base migrada y sembrada.
