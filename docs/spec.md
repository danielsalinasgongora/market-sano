<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Especificación Técnica Completa: Market Sano (Proyecto Comunitario MCP-First para Chile)

**Versión:** 2.0 (adoptada)
**Fecha:** 2026-11-17
**Licencia:** GPL-3.0-or-later
**Estado:** Documento de diseño y análisis comparativo, adoptado como base del desarrollo.

> **Nota de adopción (2026-11-17):** esta spec fue redactada como *Rinde La Olla* bajo AGPL-3.0. Al adoptarse para el repo público [`danielsalinasgongora/market-sano`](https://github.com/danielsalinasgongora/market-sano) se decidió: producto **Market Sano**, licencia **GPL-3.0-or-later**, multi-usuario local desde v0.1 y precios reales desde la Fase 1. Los identificadores técnicos y topics MQTT usan `marketsano`. Las decisiones de §9 resueltas quedan anotadas con ✔. El plan de ejecución activo vive en `tasks/plan.md` y `tasks/todo.md`.

---

## 0. Filosofía y Principios Rectores

Market Sano no es un clon. Es una **alternativa local-first, open-source y MCP-first** que resuelve los problemas que las apps comerciales de planificación ignoran deliberadamente: la **precisión de los precios reales** en el retail chileno y la **soberanía del usuario** sobre sus datos y su proveedor de IA.

1.  **Local-first y Docker-first:** Un único `docker compose up` debe levantar el sistema completo. No hay dependencia de servicios en la nube para el funcionamiento básico.
2.  **MCP como interfaz de primera clase:** La misma lógica de negocio que consume la interfaz web se expone como herramientas (Tools), Recursos (Resources) y Prompts MCP. Cualquier agente (Claude Desktop, Cursor, un bot propio) puede operar el sistema.
3.  **Proveedor de IA agnóstico:** La aplicación **no incluye claves de IA**. El usuario configura su propio proveedor (OpenRouter, Anthropic, Google Gemini, DeepSeek o cualquier endpoint compatible con OpenAI) mediante variables de entorno o un archivo de configuración local. El sistema debe ser **100% funcional sin IA**.
4.  **Privacidad por defecto:** Las credenciales de supermercados y las claves de IA nunca salen del contenedor local. No hay telemetría ni rastreo.
5.  **Modularidad real:** Cada dominio (recetas, inventario, planes, listas, gastos, Home Assistant) es un módulo con tablas y endpoints propios. Se pueden activar o desactivar mediante configuración.
6.  **Trazabilidad del precio:** Cada precio mostrado debe llevar metadatos de origen (`source`), fecha (`fetched_at`) y nivel de confianza (`confidence`). Un precio "cached" de hace 12 horas no es lo mismo que uno "live".

---

## 1. Análisis de Mercado y Diferenciación

Esta sección resume los problemas detectados en las soluciones existentes de planificación de comidas y las decisiones de producto que definen a Market Sano.

### 1.1. Problemas de las soluciones existentes

- **Precios estimados, no reales:** parten de referencias nacionales ajustadas por cadena, de modo que el total en caja **siempre** difiere del mostrado. Para Chile, esto es inaceptable.
- **Paywall agresivo:** la funcionalidad completa queda tras una suscripción, a menudo justo después de elegir el supermercado.
- **Producto cerrado y de pago:** sin soberanía del usuario sobre sus datos ni posibilidad de operar la propia instancia.
- **Recetas monótonas:** los planes tienden a repetir cenas dentro de pocas semanas.
- **Sin interfaz para agentes:** no existe forma de automatizar el flujo (planificar → estimar → comprar → registrar) más allá de la app oficial.
- **Sin integración con el hogar:** ninguna conexión con Home Assistant ni con la red local del usuario.

### 1.2. Decisiones de producto de Market Sano

| Característica | **Decisión** |
| :--- | :--- |
| **Enfoque principal** | **Presupuesto estricto + UX superior para todas las comidas** |
| **Precios** | **Precios reales vía conectores locales (Jumbo, Santa Isabel, Unimarc, …)** |
| **Modelo de negocio** | **100% Gratuito y Open-Source (GPL-3.0-or-later)** |
| **Onboarding** | **Sin cuenta (modo local `none`) o cuenta local opcional** |
| **Experiencia de cocina** | **Modo Cocina avanzado (timers, pantalla siempre activa) + integración con Home Assistant** |
| **Intercambio de comidas** | **Reequilibrio automático y opción de "dividir la compra"** |
| **Despensa** | **Sí, con movimientos y alertas de vencimiento** |
| **Integración con agentes** | **MCP nativo (Tools, Resources, Prompts)** |
| **Integración con HA** | **Sí (REST, MQTT Discovery, Custom Component)** |
| **Variedad** | **Sin repetir recetas en 4 semanas (configurable) + aprendizaje de gustos por calificación** |
| **Sobras** | **"Cocina una vez, come dos veces": planificación de sobras y "noche libre"** |

---

## 2. Arquitectura de Contenedores y Flujo de Datos

### 2.1. Diagrama Lógico de Contenedores

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                           docker-compose (perfil "full")                     │
│                                                                             │
│  ┌─────────────────────┐      ┌─────────────────────┐      ┌─────────────────────┐
│  │  Frontend (Web/PWA) │◄────►│  Backend API        │◄────►│  MCP Server         │
│  │  (SvelteKit)        │      │  (FastAPI)          │      │  (FastMCP, stdio +  │
│  │                     │      │                     │      │   HTTP SSE/Stream)  │
│  └─────────────────────┘      └──────────┬──────────┘      └──────────┬──────────┘
│                                          │                            │
│                                   ┌──────▼──────┐              ┌──────▼──────┐
│                                   │  SQLite     │              │  Módulo de  │
│                                   │  (o Postgres│              │  Adaptador  │
│                                   │   opcional) │              │  de IA      │
│                                   └─────────────┘              │  (OpenAI-   │
│                                                                 │  compatible)│
│  ┌─────────────────────┐      ┌─────────────────────┐          └─────────────┘
│  │  Broker MQTT        │◄────►│  Módulo de          │
│  │  (Mosquitto,        │      │  Publicación HA     │
│  │   opcional)         │      │  (paho-mqtt)        │
│  └─────────────────────┘      └─────────────────────┘
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Conector de Supermercados (OPCIONAL, local, no en la nube)         │   │
│  │  `mcp-supermercados-cl` o adaptador propio (Jumbo, Lider, etc.)      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Nota crítica sobre el conector de supermercados:** `mcp-supermercados-cl` es 100% local y usa transporte stdio. Unimarc, Tottus y Líder bloquean el tráfico de datacenter; requieren la IP residencial del usuario. Por lo tanto, el conector no puede desplegarse en un VPS público. En la arquitectura Docker, debe ejecutarse en la misma máquina del usuario (o en la red doméstica) y el backend debe consumirlo como un proceso local o mediante un proxy local. Si el usuario despliega en un VPS, el sistema debe degradar con gracia a "precio manual" o "caché previa".

> **Actualización (verificada 2026-11-17, upstream v1.4.9):** el bloqueo de Líder/Tottus es por **fingerprint del cliente (TLS/JA3 + desafío JS)**, no por IP — requieren un puente de navegador del usuario. Jumbo, Santa Isabel y Unimarc responden a fetch directo. Para v0.1 las cadenas objetivo son **Jumbo + Santa Isabel + Unimarc**; Líder/Tottus quedan para una fase posterior (puente de navegador).

### 2.2. Flujo Completo de un Agente (MCP) — Ejemplo Canónico

El siguiente flujo debe poder ejecutarse llamando exclusivamente a herramientas MCP, sin tocar la interfaz web:

1. El agente llama a `get_household_context()` → obtiene `household_id`, `weekly_budget_clp`, `default_store_id`, `dietary_restrictions`.
2. El agente llama a `search_recipes(query="", max_cost_per_serving=3500, tags=["sin_gluten"])` → obtiene una lista de recetas candidatas.
3. El agente llama a `create_meal_plan(week_start="2026-11-23", budget_clp=45000, constraints={...})` → el sistema crea un plan en estado `draft` (borrador). El algoritmo de generación selecciona cenas variadas (sin repetir en 4 semanas) y reequilibra automáticamente si el usuario luego intercambia una comida.
4. El agente llama a `estimate_meal_plan_cost(plan_id="...", store_ids=["jumbo", "santaisabel"])` → el sistema consulta el conector de supermercados y devuelve el costo total por cadena.
5. El agente presenta el plan al humano. El humano debe confirmar explícitamente en la interfaz web (o mediante una acción separada con token de confirmación). El agente no puede llamar a `confirm_meal_plan` sin aprobación humana.
6. Una vez confirmado, el agente llama a `generate_shopping_list(plan_id="...")` → el sistema descuenta el inventario disponible y genera la lista, agrupada por pasillo.
7. El agente llama a `compare_basket_across_stores(list_id="...")` → devuelve el total por cadena y los ítems donde conviene dividir la compra.
8. Post-compra, el humano o un agente autorizado llama a `record_actual_purchase(list_id="...", store_id="...", total_clp=...)` para cerrar el ciclo presupuestario.

**Regla de seguridad MCP:** Las tools de escritura en estado `draft` pueden ejecutarse sin confirmación. Las tools que cambian el estado a `confirmed` o que registran gastos reales siempre requieren un token de confirmación de un humano (obtenido en la UI o mediante un flujo OAuth local). Esto evita que un agente "decida" comprar o gastar por su cuenta.

---

## 3. Módulos Detallados

### 3.1. Módulo de Hogar y Autenticación

**Propósito:** Soportar uno o varios hogares por instancia, con roles y preferencias compartidas, con cero fricción en el onboarding.

**Funciones**

- **Modo Single-User (sin login):** Para instalaciones caseras. La app arranca con un hogar por defecto y no solicita credenciales. Se activa con `AUTH_MODE=none`.
- **Modo Multi-Usuario (opcional):** Registro local (email + contraseña hasheada con Argon2) o login con proveedor OIDC (Authelia, Keycloak) para instalaciones familiares o de grupos.
- **Gestión de Hogares:** CRUD de hogares (households). Cada hogar tiene nombre, moneda (CLP por defecto), zona horaria y presupuesto semanal por defecto.
- **Miembros y Roles:** Un usuario puede pertenecer a varios hogares. Roles: `owner`, `member`, `viewer`.
- **Preferencias del Hogar:** Restricciones dietéticas (JSON array), alergias (filtros duros), ingredientes que nunca se compran, supermercado habitual, comuna (para filtros de disponibilidad).
- **Invitaciones:** Generación de un código alfanumérico de un solo uso, válido por 24 horas, para unirse a un hogar.

**Entidades y Campos**

| Tabla | Campos | Notas |
|---|---|---|
| `users` | id (UUID), email (unique), password_hash, display_name, created_at, updated_at | Opcional en modo single-user |
| `households` | id, name, currency (default 'CLP'), timezone, default_weekly_budget_clp, created_at | |
| `household_members` | id, household_id (FK), user_id (FK), role (enum), joined_at | Unique (household_id, user_id) |
| `household_preferences` | household_id (PK), default_store_id, dietary_restrictions (JSONB), allergies (JSONB), never_buy (JSONB), comuna | Una fila por hogar |
| `invitations` | id, household_id, code (unique), created_by, expires_at, used_at | |

**Herramientas MCP**

| Tool | Parámetros | Retorno | Descripción |
|---|---|---|---|
| `get_household_context` | household_id (opcional) | {id, name, currency, weekly_budget_clp, default_store, dietary_restrictions, ...} | Lectura de configuración. |
| `update_household_preferences` | household_id, preferences (objeto parcial) | {updated_preferences} | Requiere rol owner o member. |

### 3.2. Módulo de Recetas

**Propósito:** El núcleo de datos. Debe permitir crear, importar, escalar y buscar recetas con ingredientes estructurados, incorporando variedad garantizada y aprendizaje de gustos.

**Funciones**

- **CRUD de Recetas:** Título, descripción, porciones base (`base_servings`), tiempo de preparación (`prep_minutes`), tiempo de cocción (`cook_minutes`), dificultad, instrucciones (Markdown).
- **Ingredientes Estructurados:** Cada ingrediente apunta a un `product_id` del catálogo normalizado. Campos: cantidad, unidad, opcional, notas.
- **Pasos Ordenados:** Lista ordenada de pasos (`recipe_steps`).
- **Etiquetas y Colecciones:** `recipe_tags` y `recipe_collections`.
- **Escalado Automático:** `scale_recipe(recipe_id, target_servings)` ajusta las cantidades. Regla de redondeo: para unidades no divisibles (huevos), redondear hacia arriba; para peso/volumen, mantener un decimal.
- **Cálculo de Costo por Porción:** `get_recipe_cost(recipe_id, store_id)` consulta el último `price_snapshot` de cada ingrediente y divide por las porciones base.
- **Sistema de Calificación y Aprendizaje:** El usuario califica una receta (1–5). El sistema usa estas calificaciones para priorizar recetas similares en futuras generaciones de planes.
- **Variedad Garantizada:** El generador de planes evita repetir la misma receta en un período configurable (por defecto, 4 semanas).
- **Importación:**
  - **Desde URL:** Scraping de JSON-LD (`recipe-scrapers`).
  - **Desde Texto Pegado:** El usuario pega una receta en texto libre. El sistema crea un `recipe_import_job` y, si hay IA configurada, la usa para estructurarla.
  - **Desde Video (v2, opcional):** Transcripción de audio + extracción con IA.
- **Búsqueda y Filtros:** `search_recipes` soporta filtros combinables: query, tags (AND), `max_cost_per_serving`, `max_time_minutes`, `only_with_pantry_match`.

**Entidades y Campos**

| Tabla | Campos | Notas |
|---|---|---|
| `recipes` | id, household_id (FK, nullable), title, description, base_servings, prep_minutes, cook_minutes, difficulty, instructions, source_url, created_by, created_at, updated_at | household_id NULL = receta pública/comunitaria |
| `recipe_ingredients` | id, recipe_id (FK), product_id (FK), quantity, unit, optional, notes, sort_order | |
| `recipe_steps` | id, recipe_id (FK), step_number, instruction, duration_minutes | |
| `recipe_tags` | recipe_id (FK), tag | PK compuesta |
| `recipe_ratings` | id, recipe_id, user_id, rating (1-5), rated_at | Base del aprendizaje de gustos |
| `recipe_collections` | id, household_id, name | |
| `recipe_collection_items` | collection_id, recipe_id | |
| `recipe_import_jobs` | id, household_id, source_type, source_value, status, result_json, error_message, created_at, completed_at | |

**Herramientas MCP**

| Tool | Parámetros | Retorno | Escribe |
|---|---|---|---|
| `search_recipes` | query, tags[], max_cost_per_serving, max_time_minutes, only_with_pantry_match | [{recipe_id, title, cost_per_serving, time_minutes, tags, avg_rating}] | No |
| `get_recipe` | recipe_id | {recipe completa} | No |
| `create_recipe` | recipe_data, dry_run (default true) | {recipe_id} o {preview} | Sí |
| `import_recipe` | source_type, source_value, dry_run | {job_id} o {preview} | Sí |
| `scale_recipe` | recipe_id, target_servings | {scaled_ingredients} | No |
| `rate_recipe` | recipe_id, rating (1-5) | {average_rating} | Sí |

### 3.3. Módulo de Inventario / Despensa

**Propósito:** Saber qué hay en casa para descontarlo del costo de la lista y evitar compras duplicadas.

**Funciones**

- **Registro de Ítems:** Producto, cantidad, unidad, ubicación (refrigerador, congelador, alacena, otro), fecha de compra, fecha de vencimiento.
- **Movimientos (`pantry_movements`):** Cada cambio de cantidad genera un movimiento con delta, reason (`purchase`, `recipe_consumption`, `manual_adjustment`, `spoilage`), reference_id.
- **Descuento Automático al Generar Lista:** La lista de compras resta la cantidad disponible en inventario.
- **Alertas de Vencimiento:** `get_pantry_status(expiring_within_days=3)` devuelve ítems próximos a vencer.
- **Normalización de Unidades:** Todas las cantidades se almacenan en una unidad canónica por producto (g, ml, unidad).

**Entidades y Campos**

| Tabla | Campos | Notas |
|---|---|---|
| `product_catalog` | id, canonical_name (unique), category, default_unit, purchase_unit, purchase_size, aliases (JSONB) | Catálogo interno normalizado. |
| `pantry_items` | id, household_id, product_id, quantity, unit, location, purchased_at, expires_at | |
| `pantry_movements` | id, pantry_item_id, delta, reason, reference_id, created_at | |

**Herramientas MCP**

| Tool | Parámetros | Retorno | Escribe |
|---|---|---|---|
| `get_pantry_status` | location (opcional), expiring_within_days (opcional) | [{product_id, product_name, quantity, unit, location, expires_at}] | No |
| `add_pantry_item` | product_id, quantity, unit, location, expires_at | {pantry_item_id} | Sí |
| `consume_pantry_item` | product_id, quantity, unit, reason | {remaining_quantity} | Sí |
| `get_pantry_shortfall` | required_ingredients: [{product_id, quantity, unit}] | [{product_id, required, available, shortfall}] | No |

### 3.4. Módulo de Planificación de Comidas y Presupuesto

**Propósito:** El flujo estrella. Planificar por presupuesto y comparar el costo real antes de comprar, con reequilibrio automático de la semana.

**Funciones**

- **Planificador Semanal:** `meal_plans` con `week_start`, `budget_clp`, `status` (`draft`, `confirmed`, `archived`).
- **Entradas del Plan (`meal_plan_entries`):** date, meal_slot (desayuno, almuerzo, cena, snack), recipe_id, servings_multiplier.
- **Modo Presupuesto Estricto:** Al crear un plan, el sistema sugiere recetas cuyo costo total no supere el `budget_clp`.
- **Reequilibrio Automático:** Si el usuario intercambia una cena (`swap_meal`), el sistema recalcula automáticamente el resto de la semana para mantenerse dentro del presupuesto. La UI debe mostrar el "ahorro" o "exceso" de cada swap.
- **Modo "Noche Libre":** El planificador puede reservar una noche para sobras o comida para llevar, contabilizándola en el presupuesto.
- **Estimación de Costo en Tiempo Real:** `estimate_meal_plan_cost(plan_id, store_ids[])` agrega los ingredientes, consulta el conector de supermercados y devuelve el total por cadena.
- **Historial y Snapshots:** Cada estimación se guarda en `budget_snapshots`.

**Entidades y Campos**

| Tabla | Campos | Notas |
|---|---|---|
| `meal_plans` | id, household_id, week_start, budget_clp, status, created_by, created_at, confirmed_at | Unique (household_id, week_start) |
| `meal_plan_entries` | id, plan_id, date, meal_slot, recipe_id, servings_multiplier, sort_order | |
| `budget_snapshots` | id, plan_id, store_id, total_clp, breakdown (JSONB), fetched_at | |

**Herramientas MCP**

| Tool | Parámetros | Retorno | Escribe |
|---|---|---|---|
| `create_meal_plan` | week_start, budget_clp, household_id, constraints | {plan_id, status: "draft"} | Sí |
| `set_meal_plan_entry` | plan_id, date, meal_slot, recipe_id, servings_multiplier | {entry_id} | Sí (solo draft) |
| `estimate_meal_plan_cost` | plan_id, store_ids[] | [{store_id, total_clp, breakdown}] | No |
| `swap_meal` | plan_id, entry_id, new_recipe_id | {new_entry, new_estimated_cost, rebalanced_plan} | Sí (solo draft) |
| `confirm_meal_plan` | plan_id, confirmation_token | {status: "confirmed"} | Sí (requiere token) |
| `get_budget_status` | plan_id | {budget_clp, estimated_clp, variance_clp, status} | No |

### 3.5. Módulo de Listas de Compras y Comparación de Precios (Chile)

**Propósito:** Convertir el plan confirmado en una lista accionable, con precios reales y comparación entre cadenas, priorizando la organización por pasillo.

**Funciones**

- **Generación desde Plan:** Agrega ingredientes, descuenta inventario y redondea a unidades de compra (packs = `ceil(aggregated_canonical_quantity / purchase_size)`).
- **Lista Manual:** El usuario puede agregar ítems sueltos.
- **Categorización por Pasillo:** Cada ítem se agrupa por `category` para ordenar el recorrido. La UI debe permitir reordenar los pasillos según el layout del supermercado del usuario.
- **Comparación de Precios entre Cadenas:** `compare_basket_across_stores(list_id)` devuelve el precio en cada cadena, el total del carro por cadena, los ítems donde una cadena es más barata y una sugerencia de "dividir la compra" si el ahorro supera un umbral.
- **Precio por Unidad de Medida (PPUM):** Obligatorio por normativa chilena. Cada `price_snapshot` almacena `unit_price_clp`.
- **Trazabilidad del Precio:** Cada snapshot tiene `source` (`live`, `cached`, `manual`), `fetched_at` y `confidence` (`high`, `medium`, `low`). La UI debe mostrar la fecha y una advertencia si `confidence` es `low`.
- **Modo Offline:** La lista debe poder exportarse a texto/CSV o guardarse en caché local.

**Entidades y Campos**

| Tabla | Campos | Notas |
|---|---|---|
| `shopping_lists` | id, household_id, plan_id (nullable), name, status, created_at, completed_at | |
| `shopping_list_items` | id, list_id, product_id, required_quantity, unit, checked, actual_price_clp, store_id | |
| `price_snapshots` | id, product_id, store_id, price_clp, unit_price_clp, is_promotion, source, confidence, fetched_at | Índice en (product_id, store_id, fetched_at DESC) |
| `store_connectors` | id, name, type, enabled, config (JSONB) | Configuración del conector |

**Herramientas MCP**

| Tool | Parámetros | Retorno | Escribe |
|---|---|---|---|
| `generate_shopping_list` | plan_id, store_ids[] | {list_id, items: [{product, quantity, unit, category}]} | Sí |
| `get_shopping_list` | list_id, group_by ("aisle" o "store") | {items agrupados} | No |
| `compare_basket_across_stores` | list_id | [{store_id, store_name, total_clp, item_comparison}] | No |
| `update_shopping_list_item` | item_id, checked, actual_price_clp | {updated_item} | Sí |
| `record_actual_purchase` | list_id, store_id, total_clp, receipt_data | {expense_id} | Sí (requiere token) |

### 3.6. Módulo de Gastos y Finanzas del Hogar

**Propósito:** Cerrar el ciclo presupuesto → compra → gasto real.

**Funciones**

- **Registro de Gasto Real:** `record_expense(household_id, amount_clp, store_id, date, category_id?, items?)`.
- **Comparación Presupuestado vs. Real:** `get_budget_variance(period_start, period_end)`.
- **Resumen por Categoría/Cadena:** `get_spending_summary(group_by="category"|"store")`.
- **Exportación:** CSV/JSON de todos los gastos del período.

**Entidades y Campos**

| Tabla | Campos | Notas |
|---|---|---|
| `expenses` | id, household_id, store_id (nullable), amount_clp, date, category_id (nullable), notes, created_at | |
| `expense_items` | id, expense_id, product_id, quantity, unit, unit_price_clp | Opcional |
| `expense_categories` | id, name (unique) | Semilla con valores por defecto |

**Herramientas MCP**

| Tool | Parámetros | Retorno | Escribe |
|---|---|---|---|
| `record_expense` | household_id, amount_clp, store_id, date, items[] | {expense_id} | Sí |
| `get_spending_summary` | period_start, period_end, group_by | {total_clp, breakdown} | No |
| `get_budget_variance` | period_start, period_end | {budgeted_clp, actual_clp, variance_clp, status} | No |

### 3.7. Módulo MCP Server (FastMCP)

**Propósito:** Exponer todas las operaciones como herramientas, recursos y prompts MCP estables, con permisos.

**Pilares de FastMCP**

- **Tools:** Ejecutan código (como POST).
- **Resources:** Cargan datos en contexto (como GET).
- **Prompts:** Plantillas reutilizables para interacciones con LLM.

**Transporte**

- **stdio:** Para clientes locales (Claude Desktop, Cursor). Modo principal.
- **HTTP (SSE o Streamable HTTP):** Para agentes remotos en la red local.

**Resources MCP**

| Resource URI | Descripción |
|---|---|
| `household://{id}/context` | Configuración completa del hogar |
| `meal-plan://{id}` | Plan de comidas completo |
| `shopping-list://{id}` | Lista de compras con ítems |
| `pantry://{household_id}/status` | Estado del inventario |

**Prompts MCP**

| Prompt | Descripción |
|---|---|
| `plan_week_within_budget` | Genera un plan semanal respetando presupuesto y restricciones. |
| `suggest_meals_from_pantry` | Sugiere recetas basadas en el inventario. |
| `compare_current_basket` | Guía al LLM para comparar la lista entre cadenas. |

**Sistema de Permisos por Tool**

- `viewer`: solo tools de lectura.
- `member`: tools de escritura en draft.
- `owner` + `confirmation_token`: tools que confirman o registran gastos.

**Dry-Run y Preview**

Todas las tools de escritura deben aceptar `dry_run: bool = True`. Si es True, devuelven una previsualización sin escribir en la base de datos.

### 3.8. Módulo de Adaptador de IA (Agnóstico al Proveedor)

**Propósito:** Permitir que el usuario conecte su propia API key sin imponer un proveedor.

**Configuración** (variables de entorno o archivo `config.toml`):

- `AI_PROVIDER`: `openrouter`, `anthropic`, `gemini`, `deepseek`, `openai_compatible`, `none`.
- `AI_API_KEY`: La clave del usuario. Nunca en la base de datos.
- `AI_MODEL`: Ej. `anthropic/claude-sonnet-4-20250514`.
- `AI_BASE_URL`: Para proveedores compatibles con OpenAI.

**Funciones que usan IA (opcionales)**

- Estructuración de recetas desde texto pegado.
- Extracción de recetas desde transcripciones de video.
- Generación asistida de planes semanales.
- Sugerencias de recetas basadas en inventario.

**Regla de privacidad:** La app nunca envía a la API de IA los precios de supermercado, las credenciales de sesión ni los datos de gastos.

### 3.9. Módulo de Importación / Exportación y Respaldo

**Funciones**

- **Exportación Completa:** JSON y CSV de todas las tablas.
- **Importación desde Mealie:** Mapeo de `recipe.name`, `recipeIngredient`, `recipeInstructions`, `recipeCategory`/keywords.
- **Importación desde Tandoor:** Tandoor exporta JSON; se puede reutilizar la lógica de Mealie.
- **Respaldo Automático:** Volumen Docker (`./backups`) y job programado (cron) que exporta la base de datos cada 24 horas.

### 3.10. Módulo de Interfaz de Usuario (Web Responsive + PWA)

**Vistas Mínimas para el MVP**

- **Dashboard del Hogar:** Presupuesto de la semana (barra de progreso), plan actual, lista pendiente, gasto real acumulado.
- **Recetario:** Búsqueda con filtros, tarjetas con costo estimado y calificación promedio, detalle de receta con ingredientes escalables y pasos.
- **Planificador Semanal:** Vista de calendario con arrastrar y soltar, costo total visible, indicador de "dentro del presupuesto" / "excedido", botón de "reequilibrar".
- **Lista de Compras:** Ítems agrupados por pasillo, checkboxes, tabla de comparación por cadena, botón de exportación.
- **Modo Cocina:** Pantalla completa con pasos grandes, temporizadores integrados y pantalla que no se apaga.
- **Inventario:** Lista de ítems con cantidad, ubicación y vencimiento, alertas visuales.
- **Configuración:** Preferencias del hogar, configuración de IA, supermercados, miembros e invitaciones.

**Stack**

- SvelteKit (recomendado) o React (Vite).
- Servido como archivos estáticos desde el backend (FastAPI StaticFiles).
- PWA: `manifest.json` y service-worker para que la lista de compras funcione offline.

### 3.11. Módulo de Docker y Despliegue

**Servicios del `docker-compose.yml`**

| Servicio | Imagen / Build | Perfil | Dependencias |
|---|---|---|---|
| `app` | Build local (FastAPI + frontend) | minimal, standard, full | db (opcional) |
| `db` | `postgres:16-alpine` (opcional; si no, SQLite) | standard, full | — |
| `mqtt` | `eclipse-mosquitto:2` | full (opcional) | — |
| `connector` | `mcp-supermercados-cl` (proceso local) | full (opcional) | app |

**Perfiles**

- **minimal:** app con SQLite. Sin Postgres, sin MQTT, sin conector. Precios manuales.
- **standard:** app + db (Postgres) + MCP server. Precios manuales o desde API externa.
- **full:** Todo lo anterior + mqtt + connector. Para integración con Home Assistant y precios reales.

**Variables de Entorno (`.env.example`)**

```env
# Base de datos
DATABASE_URL=sqlite:///./data/app.db
# o: DATABASE_URL=postgresql://user:pass@db:5432/marketsano

# Autenticación
AUTH_MODE=none  # none | local | oidc

# IA (opcional)
AI_PROVIDER=none
AI_API_KEY=
AI_MODEL=
AI_BASE_URL=

# MCP
MCP_TRANSPORT=stdio  # stdio | http
MCP_HTTP_PORT=8765

# Home Assistant (opcional)
MQTT_BROKER_URL=mqtt://mqtt:1883
MQTT_ENABLED=false

# Conector de supermercados (opcional)
SUPERMERCADOS_ENABLED=false
```

**Healthchecks y Migraciones**

- `app` debe tener `/health` que devuelva `{"status": "ok", "db": "connected"}`.
- Al arrancar, `app` ejecuta `alembic upgrade head`.
- Imagen multi-arquitectura (`linux/amd64`, `linux/arm64`).

---

## 4. Integración con Home Assistant (Módulo Transversal)

La integración con HA no es un módulo aislado, sino una capa de exposición que consume la API REST o los eventos MQTT del backend.

### 4.1. Nivel 1: Sensores REST y Comandos (MVP)

Sensores (`rest` en `configuration.yaml` de HA):

```yaml
sensor:
  - platform: rest
    name: "Presupuesto semanal restante"
    resource: "http://tu-app:8000/api/v1/households/1/dashboard"
    value_template: "{{ value_json.budget_remaining_clp }}"
    unit_of_measurement: "CLP"
    scan_interval: 300

  - platform: rest
    name: "Ítems pendientes lista de compras"
    resource: "http://tu-app:8000/api/v1/shopping-lists/active"
    value_template: "{{ value_json.pending_items_count }}"
```

Comandos (`rest_command`):

```yaml
rest_command:
  agregar_item_lista:
    url: "http://tu-app:8000/api/v1/shopping-lists/1/items"
    method: POST
    headers:
      Authorization: "Bearer TU_API_KEY"
      Content-Type: "application/json"
    payload: '{"product_id": "{{ product_id }}", "quantity": {{ quantity }}}'
```

**Requisito en el backend:** Exponer endpoints REST limpios y documentados con OpenAPI/Swagger.

### 4.2. Nivel 2: MQTT con Descubrimiento Automático (v1)

**Publicación de Estado:** El backend publica en topics como:

- `marketsano/{household_id}/budget/remaining`
- `marketsano/{household_id}/shopping_list/pending_count`
- `marketsano/{household_id}/meal_plan/today_recipe`

**Descubrimiento Automático (MQTT Discovery):** El backend publica un mensaje de configuración en `homeassistant/device/<object_id>/config`. El payload JSON describe el dispositivo y sus componentes (`cmps`), cada uno con platform (`p`) y unique_id (`uniq_id`).

Ejemplo de payload:

```json
{
  "device": {
    "identifiers": ["marketsano_household_1"],
    "name": "Market Sano Hogar 1",
    "manufacturer": "Market Sano Open Source",
    "model": "Meal Planner"
  },
  "origin": { "name": "Market Sano Backend" },
  "components": {
    "budget_remaining": {
      "platform": "sensor",
      "name": "Presupuesto restante",
      "unit_of_measurement": "CLP",
      "state_topic": "marketsano/1/budget/remaining",
      "unique_id": "marketsano_1_budget_remaining"
    },
    "pending_shopping_items": {
      "platform": "sensor",
      "name": "Ítems pendientes",
      "state_topic": "marketsano/1/shopping_list/pending_count",
      "unique_id": "marketsano_1_shopping_pending"
    }
  }
}
```

**Requisito en el backend:** Añadir `paho-mqtt` y un módulo que publique estos mensajes al arrancar y cada vez que cambie un estado relevante.

### 4.3. Nivel 3: Custom Component + Add-on (v2)

**Custom Component:**

- Ubicación: `custom_components/marketsano/`.
- **Config Flow:** El usuario añade la integración desde la UI de HA, introduce la URL de su instancia y una API key de larga duración.
- **Entidades expuestas:**
  - `sensor.marketsano_presupuesto_restante`
  - `sensor.marketsano_gasto_semanal`
  - `sensor.marketsano_items_pendientes_lista`
  - `sensor.marketsano_receta_del_dia`
- **Acciones (Services):**
  - `marketsano.generar_plan_semanal`
  - `marketsano.agregar_item_lista`
  - `marketsano.registrar_gasto`
  - `marketsano.marcar_item_comprado`

**Add-on (para HAOS):**

- Empaquetar el contenedor de Market Sano como un add-on de HA. Repositorio con `config.yaml` para el Supervisor.
- Publicarlo en HACS.

**Autenticación:** La integración de HA utiliza un token de larga duración generado en el perfil de Market Sano.

---

## 5. Modelo de Datos Completo (Resumen de Tablas)

| Tabla | Propósito | Campos Clave |
|---|---|---|
| `users` | Usuarios locales | id, email, password_hash, display_name |
| `households` | Hogares | id, name, currency, timezone, default_weekly_budget_clp |
| `household_members` | Pertenencia y roles | household_id, user_id, role |
| `household_preferences` | Preferencias | household_id, default_store_id, dietary_restrictions, allergies, comuna |
| `invitations` | Códigos de invitación | code, household_id, expires_at, used_at |
| `product_catalog` | Catálogo normalizado | id, canonical_name, category, default_unit, purchase_unit, purchase_size, aliases |
| `recipes` | Recetas | id, household_id, title, base_servings, prep_minutes, cook_minutes, instructions |
| `recipe_ingredients` | Ingredientes | recipe_id, product_id, quantity, unit, optional |
| `recipe_steps` | Pasos | recipe_id, step_number, instruction |
| `recipe_tags` | Etiquetas | recipe_id, tag |
| `recipe_ratings` | Calificaciones | recipe_id, user_id, rating |
| `recipe_collections` | Colecciones | id, household_id, name |
| `recipe_import_jobs` | Jobs de importación | id, source_type, status, result_json |
| `pantry_items` | Inventario | id, household_id, product_id, quantity, location, expires_at |
| `pantry_movements` | Movimientos | id, pantry_item_id, delta, reason, reference_id |
| `meal_plans` | Planes semanales | id, household_id, week_start, budget_clp, status |
| `meal_plan_entries` | Entradas del plan | id, plan_id, date, meal_slot, recipe_id |
| `budget_snapshots` | Estimaciones históricas | id, plan_id, store_id, total_clp, fetched_at |
| `shopping_lists` | Listas de compras | id, household_id, plan_id, status |
| `shopping_list_items` | Ítems de lista | id, list_id, product_id, required_quantity, checked |
| `price_snapshots` | Precios históricos | id, product_id, store_id, price_clp, unit_price_clp, source, confidence, fetched_at |
| `store_connectors` | Configuración de conectores | id, name, type, enabled, config |
| `expenses` | Gastos reales | id, household_id, store_id, amount_clp, date |
| `expense_items` | Desglose de gasto | id, expense_id, product_id, quantity, unit_price_clp |
| `expense_categories` | Categorías | id, name |

**Índices Críticos:**

- `price_snapshots(product_id, store_id, fetched_at DESC)`
- `meal_plan_entries(plan_id, date)`
- `pantry_items(household_id, product_id)`
- `shopping_list_items(list_id, checked)`

---

## 6. Stack Técnico Definitivo

| Capa | Elección | Justificación |
|---|---|---|
| Backend | Python 3.12+ + FastAPI | Maduro, tipado con Pydantic, OpenAPI automático, excelente ecosistema MCP. |
| MCP Server | FastMCP 2.x | Permite definir tools, resources y prompts con decoradores. |
| Base de Datos | SQLite (por defecto) / PostgreSQL 16 (opcional) | SQLite para `docker compose up` sin configuración. Postgres para multi-hogar. |
| ORM / Migraciones | SQLModel + Alembic | Combina Pydantic y SQLAlchemy; migraciones gestionadas. |
| Frontend | SvelteKit | Build ligero, sin Node en producción. Alternativa: React + Vite. |
| MQTT | paho-mqtt (Python) + Mosquitto (contenedor opcional) | Librería estándar para publicar en MQTT; Mosquitto es el broker de referencia. |
| IA | Adaptador OpenAI-compatible (httpx + openai SDK) | Un solo adaptador cubre OpenRouter, Anthropic, Gemini y DeepSeek. |
| Conectores de Supermercado | mcp-supermercados-cl (proceso local) o adaptador propio | No reinventar el scraping. Documentar cómo conectar el MCP existente. |
| Contenedores | Docker + docker compose | Imágenes multi-arch. Perfiles minimal, standard, full. |
| Licencia | GPL-3.0-or-later | Cópyleft fuerte que protege el carácter comunitario del proyecto. (Originalmente AGPL-3.0; decisión del mantenedor registrada en §9.1.) |

---

## 7. Seguridad y Cumplimiento Legal (Chile)

### 7.1. Ley 21.719 (Protección de Datos Personales)

Vigente desde el 1 de diciembre de 2026. La aplicación debe facilitar el cumplimiento:

- **Consentimiento Libre, Informado y Específico:** Si se habilitan múltiples usuarios, el registro debe mostrar un aviso de privacidad claro y requerir una acción afirmativa (checkbox no premarcado).
- **Finalidad Limitada:** Los datos recopilados solo se usan para el funcionamiento de la app. No hay marketing ni cesión a terceros.
- **Minimización:** No se solicita RUT, dirección exacta ni datos sensibles. La comuna es suficiente.
- **Derecho de Supresión:** El usuario debe poder eliminar su cuenta y todos sus datos asociados desde la UI (`delete_household` con cascada).
- **Sin Tracking:** La app no incluye SDKs de analytics ni rastreadores publicitarios.

### 7.2. Seguridad de Secretos

- **API Keys de IA y de supermercados:** Nunca en la base de datos. Se leen de variables de entorno o de archivos montados (`/run/secrets/`).
- **Tokens de HA:** Se generan como tokens de larga duración con permisos de solo lectura o lectura/escritura según el rol. Se almacenan hasheados en `api_tokens`.
- **Contraseñas de usuarios:** Hasheadas con Argon2id.

### 7.3. Precio por Unidad de Medida (PPUM)

Desde septiembre de 2025, el SERNAC exige informar el PPUM. Cada `price_snapshot` debe almacenar `unit_price_clp`. La comparación entre cadenas debe basarse en PPUM cuando las presentaciones difieran.

---

## 8. Roadmap por Fases

> El plan de ejecución activo vive en `tasks/plan.md` y `tasks/todo.md`. Esta sección conserva el roadmap original de la comunidad; la decisión de proyecto adelantó los **precios reales** a la Fase 1 de ejecución.

### Fase 0 — Esqueleto y Validación Técnica (Semanas 1–3)

- [ ] Crear repositorio en GitHub con `README.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` y `LICENSE` (GPL-3.0-or-later).
- [ ] Configurar `docker-compose.yml` con el perfil minimal (FastAPI + SQLite + healthcheck).
- [ ] Implementar el modelo de datos inicial con SQLModel y Alembic.
- [ ] Implementar 3 tools MCP de solo lectura: `get_household_context`, `search_recipes`, `get_pantry_status`.
- [ ] Verificar que Claude Desktop puede conectarse al MCP vía stdio y ejecutar esas tools.

**Criterio de salida:** Cualquiera puede clonar, `docker compose --profile minimal up`, y conectar Claude Desktop.

### Fase 1 — MVP Funcional (Semanas 4–11)

- [ ] CRUD de recetas con ingredientes estructurados y pasos.
- [ ] Importación de recetas desde URL (JSON-LD / recipe-scrapers).
- [ ] Inventario con movimientos y descuento en listas.
- [ ] Planificador semanal con presupuesto y cálculo de costo (precios manuales o un único conector, ej. Jumbo).
- [ ] Reequilibrio automático al intercambiar comidas.
- [ ] Lista de compras con categorización por pasillo y exportación CSV.
- [ ] Registro de gasto real simple (total por compra).
- [ ] Interfaz web mínima para todas las operaciones.
- [ ] Sensores REST para Home Assistant (Nivel 1).

**Criterio de salida:** Un hogar puede planificar una semana, generar la lista y registrar la compra real sin tocar la base de datos a mano.

### Fase 2 — v1: Precios Reales y MCP Completo (Semanas 12–23)

- [ ] Integrar `mcp-supermercados-cl` (o adaptador) para Jumbo y las cadenas de fetch directo, luego las 5 cadenas.
- [ ] Comparación de carro entre cadenas con PPUM.
- [ ] Tools MCP de escritura con `dry_run` y tokens de confirmación.
- [ ] Adaptador de IA configurable (OpenRouter, Anthropic, Gemini, DeepSeek).
- [ ] Importación desde Mealie/Tandoor.
- [ ] MQTT con descubrimiento automático (Nivel 2 de HA).
- [ ] Publicación de imágenes Docker multi-arch.

**Criterio de salida:** Un agente puede ejecutar el flujo completo (planificar → estimar → lista → comparar) con precios reales de al menos 2 cadenas.

### Fase 3 — v2: Ecosistema y Pulido (Continuo)

- [ ] Importación de recetas desde video con IA (transcripción + extracción).
- [ ] Alertas de vencimiento y sugerencias de recetas basadas en inventario.
- [ ] OCR de recibos (opcional).
- [ ] Custom Component completo de Home Assistant (Nivel 3).
- [ ] Empaquetado como Add-on para HAOS y publicación en HACS.
- [ ] PWA con soporte offline completo.
- [ ] Sistema de plugins para conectores de otros países.
- [ ] Documentación completa de la API MCP y guía de contribución.

---

## 9. Lista de Validación: Qué Falta, Qué Sobra, Qué Decidir

### 9.1. ¿Falta algo?

- **Multi-hogar vs. single-user:** ¿El MVP soporta varias familias en una instancia o una sola? → ✔ **RESUELTO (2026-11-17): multi-usuario local desde v0.1** (registro email + Argon2id, roles owner/member/viewer, invitaciones de un solo uso). `AUTH_MODE=none` sigue disponible como modo sin fricción.
- **Redondeo de unidades de compra:** ¿Cómo se convierte "1 cucharada de aceite" a "botella de 1 L"? → ✔ **Definido en el Anexo A**: unidades canónicas + `purchase_unit`/`purchase_size` en `product_catalog`; tabla de equivalencias de cocina en la semilla.
- **Confirmación humana en MCP:** ¿Qué tools requieren token? → ✔ **Adoptado:** `confirm_meal_plan` y `record_actual_purchase`; el resto escribe en draft sin token.
- **Idioma y localización:** → ✔ **Español chileno desde el día uno.** "Palta", no "aguacate".
- **Licencia:** AGPL vs. MIT vs. GPL → ✔ **RESUELTO (2026-11-17): GPL-3.0-or-later** (decisión del mantenedor, sobrescribe el AGPL-3.0 original).
- **Nombre del proyecto:** → ✔ **RESUELTO (2026-11-17): Market Sano** (renombrado desde "Rinde La Olla").

### 9.2. ¿Sobra algo (que puede esperar)?

- **App móvil nativa:** No es necesaria para el MVP. La web responsive + MCP cubre el caso de uso.
- **OCR de recibos:** Útil pero añade dependencias pesadas. Es v2.
- **Importación desde video:** Requiere transcripción + IA. Es v2.
- **Multi-moneda:** Chile usa CLP. No complicar el modelo hasta que haya demanda de otros países.
- **Gamificación / notificaciones push:** No aportan al núcleo de presupuesto y precios reales.

### 9.3. Decisiones Técnicas Abiertas (documentar en el README)

- **¿El MCP server es el mismo proceso que el backend o un contenedor separado?** → ✔ Recomendación adoptada: **mismo código, distinto entrypoint** (`main.py` para la API, `mcp_server.py` para el MCP).
- **¿Los conectores de supermercado se ejecutan en el host o en un contenedor?** `mcp-supermercados-cl` necesita IP residencial y usa stdio. Documentar ambas opciones (`network_mode: host` o proxy local).
- **¿Cómo se manejan las credenciales de supermercado?** Nunca en la BD central. En variables de entorno del contenedor del conector o en un llavero local (keyring).
- **¿El broker MQTT se incluye en el docker-compose?** → ✔ Sí, como servicio opcional en el perfil full.

---

## 10. Anexos Técnicos

### A. Algoritmo de Redondeo y Unidades

- **Normalización a unidad canónica:** Cada producto tiene una `canonical_unit` (g, ml, unidad). Las recetas pueden expresar cantidades en unidades de cocina (cucharada, taza), que se convierten a la canónica usando una tabla de equivalencias.
- **Agregación:** Al sumar ingredientes de varias recetas, se suman en unidad canónica.
- **Conversión a unidad de compra:** El `product_catalog` tiene un `purchase_unit` (ej. "paquete de 1 kg") y un `purchase_size` (1000 g). La lista de compras sugiere `packs = ceil(aggregated_canonical_quantity / purchase_size)`.
- **Ejemplo:** 700 g de pasta requeridos, paquete de 1 kg → `ceil(700/1000)` = 1 paquete.
- **Redondeo de huevos/unidades discretas:** Siempre ceil al entero más cercano.

### B. Autenticación para Home Assistant y Agentes

- **Tokens de larga duración:** Se generan en la UI de Market Sano (`/settings/tokens`). Se muestran una sola vez y se almacenan hasheados en `api_tokens` (id, user_id, name, token_hash, scopes (JSONB), created_at, last_used_at).
- **Scopes:** `read`, `write_draft`, `confirm`, `admin`. El token de HA suele tener `read` + `write_draft`.
- **MCP HTTP:** El agente debe enviar el token en el header `Authorization: Bearer <token>`.

### C. Estructura del Repositorio (Monorepo)

```text
/
├── backend/
│   ├── app/
│   │   ├── api/          # Endpoints REST
│   │   ├── models/       # SQLModel
│   │   ├── services/     # Lógica de negocio
│   │   ├── mcp/          # Tools, resources, prompts MCP
│   │   ├── connectors/   # Adaptadores de supermercado (opcional)
│   │   ├── ai/           # Adaptador de IA
│   │   └── mqtt/         # Publicación para HA
│   ├── migrations/       # Alembic
│   └── tests/
├── frontend/             # SvelteKit
├── homeassistant/        # Custom component (v2)
├── addon/                # Configuración del add-on de HAOS (v2)
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── docs/
│   ├── mcp-tools.md
│   ├── home-assistant.md
│   └── legal-privacy.md
├── .env.example
├── README.md
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
└── LICENSE
```

> **Desviación adoptada en Market Sano:** `docker-compose.yml` vive en la **raíz** del repo (no en `docker/`) para que `docker compose up` funcione sin flags. El `Dockerfile` permanece en `docker/`.

### D. Semilla de Datos (seed_data)

El proyecto debe incluir un script de semilla con:

- 10–15 recetas chilenas básicas (cazuela, charquicán, pastel de choclo, porotos con riendas, etc.) con ingredientes estructurados.
- Un `product_catalog` inicial con ~100 productos comunes en supermercados chilenos, con sus alias ("palta"/"aguacate", "poroto"/"frijol").
- Categorías de gasto por defecto.

---

Fin del documento. Cualquier contribuidor debe poder leer este archivo y entender el alcance completo del proyecto, las decisiones ya tomadas y las que quedan pendientes. La validación de este documento por parte de la comunidad es el paso previo a la creación del repositorio público y al inicio de la Fase 0.
