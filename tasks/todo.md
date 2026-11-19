# Market Sano — Lista de Tareas

> Plan maestro y decisiones: `tasks/plan.md`. Marca `[x]` cada criterio al verificarlo.
> Regla de cierre por tarea: `pytest` verde + `ruff check` limpio + verificación manual hecha.
> v1.1: incorpora multi-usuario desde v0.1 (T13–T14) según decisión del usuario.

---

## Fase 0 — Esqueleto público y validación MCP (≈ spec Fase 0, sem. 1–3)

### Task 1: Repo público GitHub + licencia GPL-3.0-or-later + docs de comunidad
**Descripción:** Monorepo público según Anexo C de la spec en https://github.com/danielsalinasgongora/market-sano (repo creado por el usuario, URL entregada). El agente configura `origin` y hace el push inicial. Copia la spec v2.0 a `docs/spec.md` corrigiendo **licencia** (AGPL→GPL-3.0-or-later) y **nombre de producto** (Rinde La Olla→Market Sano), con anotaciones ✔ en las decisiones resueltas de §9.
**Criterios de aceptación:**
- [x] `LICENSE` con texto completo GPL v3; headers de código con SPDX `GPL-3.0-or-later`
- [x] README (español) con branding **Market Sano**, filosofía, quickstart `docker compose up`, badges CI; CONTRIBUTING.md; CODE_OF_CONDUCT.md
- [x] Estructura monorepo: `backend/app/{api,models,services,mcp,connectors,ai,mqtt}`, `backend/migrations`, `backend/tests`, `frontend/`, `docs/`, `docker/`, `docker-compose.yml` en raíz, `.env.example` (variables de spec §3.11), `.gitignore` (Python+Node+`data/`+`backups/`)
- [x] `docs/spec.md` = spec v2.0 con licencia y nombre corregidos
**Verificación:** `git clone` desde la URL pública funciona; `docker compose config` valida sin errores. ✔ Verificado 2026-11-17 (push 8b6f527 + compose config OK).
**Dependencias:** Ninguna (el push inicial requiere la URL del repo que entrega el usuario). **Tamaño:** S
**Archivos:** `LICENSE`, `README.md`, `docs/spec.md`, `.env.example`, `docker-compose.yml`, `.gitignore`

### Task 2: Backend FastAPI + Docker perfil minimal + healthcheck
**Descripción:** Esqueleto FastAPI con settings por entorno, SQLite (WAL), Alembic baseline, `/health`, Dockerfile multi-arch-ready y compose perfil `minimal` con healthcheck. `pyproject.toml` con `fastmcp<3`.
**Criterios de aceptación:**
- [x] `docker compose --profile minimal up` levanta la app en `:8000`
- [x] `GET /health` → `{"status":"ok","db":"connected"}`; `alembic upgrade head` corre al arrancar
- [x] `pytest backend/tests` y `ruff check backend` limpios desde el primer commit
**Verificación:** `docker compose --profile minimal up` + `curl localhost:8000/health`. ✔ Verificado 2026-11-17 (7 tests + ruff limpios; contenedor `Up (healthy)`; proyecto compose renombrado a `market-sano`; `.dockerignore` reduce el contexto de build de 194 MB a 2 kB).
**Dependencias:** T1. **Tamaño:** M
**Archivos:** `backend/app/main.py`, `backend/app/settings.py`, `backend/migrations/`, `docker/Dockerfile`, `docker-compose.yml`

### Task 3: Modelo de datos completo (SQLModel) + migración inicial
**Descripción:** Todas las tablas de spec §5 (users, households, household_members, household_preferences, invitations, product_catalog, recipes, recipe_ingredients, recipe_steps, recipe_tags, recipe_ratings, recipe_collections, recipe_collection_items, recipe_import_jobs, pantry_items, pantry_movements, meal_plans, meal_plan_entries, budget_snapshots, shopping_lists, shopping_list_items, price_snapshots, store_connectors, expenses, expense_items, expense_categories, api_tokens) con constraints e índices críticos.
**Criterios de aceptación:**
- [x] Migración crea todas las tablas en BD limpia; smoke test inserta/lee un registro por tabla núcleo
- [x] Índices críticos: `price_snapshots(product_id, store_id, fetched_at)` (índice plano con recorrido en reverso — un índice con expresión `desc()` no es refleable en SQLite; decisión documentada en el modelo), `meal_plan_entries(plan_id, date)`, `pantry_items(household_id, product_id)`, `shopping_list_items(list_id, checked)`
- [x] Constraints: unique `(household_id, week_start)` en meal_plans; enums nativos `role`, `plan_status`, `meal_slot`, `price_source`, `price_confidence` (+`pantry_location`, `movement_reason`, `difficulty`, import y list status) con valores limpios en minúsculas; CHECK `rating BETWEEN 1 AND 5`
**Verificación:** `pytest backend/tests -k models`; `alembic upgrade head` + `alembic downgrade base` + upgrade idempotente. ✔ Verificado 2026-11-17: 15/15 tests verdes (tests corren contra la migración real, no `create_all`); ciclo upgrade→downgrade→upgrade OK local y en contenedor (`alembic current` → `0001 (head)`); SQLModel 0.0.50 usa `UTCDateTime` que exige datetimes con timezone (refuerza la convención UTC).
**Dependencias:** T2. **Tamaño:** M
**Archivos:** `backend/app/models/`, `backend/migrations/versions/0001_initial.py`, `backend/tests/test_models.py`

### Task 4: Semilla de datos chilena
**Descripción:** Script idempotente con catálogo (~100 productos, aliases "palta"/"aguacate", "poroto"/"frijol"), 10–15 recetas chilenas estructuradas (cazuela, charquicán, pastel de choclo, porotos con riendas…), tabla de equivalencias de cocina (Anexo A), categorías de gasto, hogar por defecto (`AUTH_MODE=none`, `default_weekly_budget_clp=45000`), registry de conectores y algunos ítems de despensa de demo.
**Criterios de aceptación:**
- [x] `python -m app.seed` re-ejecutable sin duplicar (upserts; además aplica migraciones pendientes solo, funciona sobre BD recién creada)
- [x] Toda receta resuelve 100% de ingredientes a `product_id` del catálogo con unidad canónica (test por receta: unidad == `default_unit` del producto)
- [x] Cada producto tiene `default_unit` y, si es comprable, `purchase_unit`/`purchase_size` (101 productos con aliases: "palta"/"aguacate", "porotos"/"frijol")
**Verificación:** `pytest backend/tests -k seed`; CLI corrido 2 veces local y en contenedor. ✔ Verificado 2026-11-17: 20/20 tests verdes (incluye test de CLI vía subprocess); recetas muestreadas por consulta directa (el endpoint de recetas llega con T10); `despensa_demo: 0` en la segunda corrida.
**Dependencias:** T3. **Tamaño:** M
**Archivos:** `backend/app/seed.py`, `backend/app/seed_data/` (catálogo, recetas, equivalencias)

### Task 5: Servidor MCP stdio + 3 tools de lectura + docs Claude Desktop
**Descripción:** Entrypoint `mcp_server.py` (FastMCP pinneado `<3`) con `get_household_context`, `search_recipes` (versión inicial: query + tags, filtros de costo llegan en T11) y `get_pantry_status`; resource `household://{id}/context`; docs de conexión para Claude Desktop/Cursor.
**Criterios de aceptación:**
- [x] `fastmcp dev backend/app/mcp_server.py` (o inspector MCP) ejecuta las 3 tools contra la semilla — verificado con el cliente MCP de FastMCP (in-memory) **y** un roundtrip stdio real (`StdioTransport` + `python -m app.mcp_server` como subproceso, igual que Claude Desktop) en `tests/test_mcp.py`
- [x] `docs/mcp-tools.md` documenta contrato de cada tool (params/retorno/permisos/errores accionables + roadmap del contrato)
- [x] `docs/clients/claude-desktop.md` con JSON de configuración stdio reproducible (Windows/macOS/Cursor + solución de problemas)
**Verificación:** Manual: conectar Claude Desktop y ejecutar `get_household_context` → devuelve hogar sembrado. ✔ Automático verificado 2026-11-17 (28/28 tests: list_tools, call_tool, read_resource y stdio end-to-end). Conexión manual con Claude Desktop ✔ 2026-11-18.
**Dependencias:** T4. **Tamaño:** M
**Archivos:** `backend/app/mcp_server.py`, `backend/app/mcp/tools_read.py`, `docs/mcp-tools.md`, `docs/clients/claude-desktop.md`

### Task 6: CI GitHub Actions
**Descripción:** Workflow con `ruff check` + `pytest` sobre Python 3.12; badge en README. El job de frontend se añade cuando exista (T24).
**Criterios de aceptación:**
- [x] Push/PR dispara CI y pasa en verde
- [x] README muestra badge de estado
**Verificación:** Primer run verde en GitHub Actions. ✔ Verificado 2026-11-17 (run #1: ruff + pytest en Python 3.12, 39 s).
**Dependencias:** T2 (paralelizable con T3–T5). **Tamaño:** S
**Archivos:** `.github/workflows/ci.yml`, `README.md`

### ✅ Checkpoint A — Criterio de salida Fase 0 (spec)
- [x] Cualquiera puede: `git clone` → `docker compose --profile minimal up` → conectar Claude Desktop vía stdio y ejecutar las 3 tools — automatizado verificado por tests (compose + semilla + stdio roundtrip); manual con Claude Desktop ✔ 2026-11-18 (vía `docker exec`)
- [x] CI verde; `/health` OK; migraciones aplicadas (contenedor en `0001 (head)`, CI runs #1-#5 en verde)
- [x] **Revisión humana antes de Fase 1** — ✔ 2026-11-18: Claude Desktop conectado y `get_household_context` OK

---

## Fase 1 — Precios reales temprano (decisión D3; adelanta spec F2)

### Task 7: PriceService con trazabilidad (manual + caché) + PPUM
**Descripción:** Contrato estable de precios: `get_latest_price(product_id, store_id)` con prioridad live→cache→manual, metadatos `source`/`confidence`/`fetched_at` y stale-flag; API para precio manual; `unit_price_clp` (PPUM) obligatorio; TTL configurable (`PRICE_CACHE_TTL_HOURS`).
**Criterios de aceptación:**
- [x] `POST /api/v1/prices` crea snapshot `source=manual, confidence=high` con `unit_price_clp` validado
- [x] `GET /api/v1/products/{id}/price?store_id=jumbo` devuelve snapshot más reciente + metadatos + indicador de antigüedad
- [x] Tests con reloj simulado (fake clock) cubren prioridad de fuentes y TTL
**Verificación:** `pytest backend/tests -k prices`; curl de precio manual creado y leído. ✔ Verificado 2026-11-17: 8 tests nuevos (36/36 totales: POST/GET, 404/422, prioridad por frescura, TTL live→cached, manual no caduca); curl real contra el contenedor `:8000` (palta en jumbo $1.590, PPUM $1.590). `registrar_snapshot` genérico queda listo para el conector (T9). Semántica documentada: gana el snapshot más reciente; live expirado se reporta `source_efectiva=cached` + `is_stale`.
**Dependencias:** T3, T4. **Tamaño:** M
**Archivos:** `backend/app/services/prices.py`, `backend/app/api/prices.py`, `backend/tests/test_prices.py`

### Task 8: Spike del conector mcp-supermercados-cl — 🔀 PUERTA DE DECISIÓN
**Descripción:** Evaluar en la máquina del usuario (Node.js local) el paquete upstream (MIT): fetch directo Jumbo/Santa Isabel/Unimarc, latencias, formato (`price`, `listPrice`, `memberPrice`, `unitPrice`), y mapeo `canonical_name → query` para 20 productos del catálogo. Definir modo de integración (recomendado: backend como **cliente MCP** vía stdio-subprocess con FastMCP Client).
**Criterios de aceptación:**
- [x] `docs/connectors/spike-2026-11.md` con evidencia: ≥10 productos traídos live por cadena, latencias, y fallos documentados (Líder/Tottus esperados bloqueados)
- [x] Mapeo de 20 productos del catálogo resuelto a producto concreto del retailer (mejor PPUM)
- [x] Decisión escrita: integrar upstream tal cual / adaptador propio / mixto, con justificación
**Verificación:** Manual en máquina del usuario; documentar comandos exactos ejecutados. ✔ Verificado 2026-11-18: 60/60 búsquedas live (20 productos × Jumbo/Santa Isabel/Unimarc) vía `fastmcp.Client` stdio; medianas 216/194/1119 ms; Tottus 403 y Líder antibot. Regla de mapeo ingenua ~70 % de acierto → **decisión: mixto** (upstream como fuente vía cliente MCP stdio + matching propio con `product_store_matches` adelantada a T9). Impactos para T9: PPUM sin unidad en `price_snapshots`, peso medio por unidad para productos a granel, Node en la imagen `full`. Scripts en `docs/connectors/spike/`.
**Dependencias:** T7 (contrato), Node.js en host. **Tamaño:** M
**Archivos:** `docs/connectors/spike-2026-11.md`, `docs/connectors/` (evidencias)

### Task 9: Integración del conector (cliente MCP stdio) + refresco TTL + degradación elegante
**Descripción:** `connectors/supermercados_cl.py`: lanza el conector como subproceso local y habla MCP; refresca `price_snapshots` (`source=live, confidence=high`) con TTL; ante fallo devuelve caché con `confidence` degradado y advertencia; perfiles compose `standard`/`full` con el conector; documentar alternativa host-mode para el puente de navegador futuro. El refresco cubre también los productos dados de alta desde búsqueda de supermercado (T9b), usando su match por cadena.
**Criterios de aceptación:**
- [x] Con conector activo: precio de producto del catálogo refrescado a `source=live` en Jumbo
- [x] Con conector caído: respuesta degradada correcta (caché + `confidence` baja + warning) — sin excepciones al usuario
- [x] Tests con conector stub (subproceso MCP falso) cubren éxito, fallo y TTL
- [x] `docs/connectors/README.md` explica perfiles y requisitos (Node.js, IP residencial)
**Verificación:** `pytest backend/tests -k connector`; manual: bajar el conector y verificar degradación. ✔ Verificado 2026-11-18: 10 tests nuevos con conector falso por stdio real (éxito Jumbo/Unimarc por SKU, caído, comando inexistente, manual no se degrada, TTL fresco/vencido, sin match/deshabilitado, semilla idempotente); e2e con el conector real vía la API: tomate/leche/arroz/palta/pollo → `live` desde Jumbo (tomate $1.045, PPUM $314/un con peso medio 150 g); conector caído → `confidence_efectiva=low` + `warning`. Incluye fixes del spike: migración 0002 (`product_store_matches` adelantada desde T9b + `product_catalog.unit_weight_g`), convención de unidad del PPUM y 20 matches curados de Jumbo en la semilla. Dockerfile con Node 22 + conector en `/opt` (**build pendiente: Docker no estaba corriendo**). Disparo: on-demand en `GET …/price`; sin refresco masivo programado.
**Dependencias:** T8. **Tamaño:** M
**Archivos:** `backend/app/connectors/supermercados_cl.py`, `docker-compose.yml`, `backend/tests/test_connector.py`, `docs/connectors/README.md`

### Task 9b: Catálogo abierto — búsqueda en supermercado y alta de productos (decisión D8)
**Descripción:** Los usuarios pueden buscar artículos directamente en las cadenas (passthrough del conector: `search_store_products(query, store_id)`, MCP + API) y darlos de alta en su catálogo como ingredientes (`add_product_from_store`, con `dry_run` por defecto): crea/actualiza `product_catalog` con la unidad canónica inferida del resultado y guarda el match por cadena (URL/SKU) en la nueva tabla `product_store_matches` (migración 0002), para que el refresco de precios (T9) los mantenga actualizados.
**Criterios de aceptación:**
- [x] `search_store_products` (MCP + API) devuelve resultados enriquecidos del conector (nombre, marca, precio, PPUM, URL) sin escribir nada
- [x] `add_product_from_store` crea el producto con unidad canónica inferida y el match por cadena; `dry_run=true` devuelve preview sin escribir
- [x] Los productos con match quedan dentro del ciclo de refresco TTL de T9 (prueba con conector stub)
- [x] Migración 0002 con `product_store_matches(product_id, store_id, store_url, sku, matched_at)` e índice `(product_id, store_id)` — hecha en T9 (unique `(product_id, store_id)`)
**Verificación:** `pytest backend/tests -k catalogo_abierto`; manual: buscar un artículo en jumbo desde el inspector MCP y agregarlo al catálogo. ✔ Verificado 2026-11-18: 8 tests nuevos (API + tools MCP in-memory con conector falso stdio: búsqueda sin escritura, 503 deshabilitado, dry_run, crear + precio live por SKU en Unimarc, vincular/reemplazar sin duplicar, unidad incompatible 422) + 1 test en T9 (match reemplazado invalida el live anterior). E2E con conector real vía API: "quinoa" buscada en Jumbo → alta (g, pack 250 g) → precio live $2.250 (PPUM $9.000/kg); "leche" vinculada en Santa Isabel → live $990. Manual con inspector MCP: pendiente del usuario. Endpoints: `GET /api/v1/stores/{store_id}/products`, `POST /api/v1/products/from-store?dry_run=`.
**Dependencias:** T9. **Tamaño:** M
**Archivos:** `backend/app/api/products.py`, `backend/app/mcp/tools_catalog.py`, `backend/app/models/catalog.py`, `backend/migrations/versions/0002_*.py`

### ✅ Checkpoint B — Precios reales operativos
- [x] Costo de una receta semilla calculado con precio **live de Jumbo** y con precio manual; ambos con metadatos correctos — 2026-11-18, Charquicán re-verificado con `get_recipe_cost` (T11): **$10.517 total / $2.629 por porción**, 5 ingredientes live + 5 manuales, cada línea con `source`/`confidence`/`unit_price_clp`/`is_stale`
- [x] Degradación live→cache→manual verificada end-to-end — conector caído real (`SUPERMERCADOS_COMMAND` inexistente, TTL=0): respuesta `source=live` → `source_efectiva=cached`, `confidence_efectiva=low`, `is_stale=true` + `warning`; sin excepciones
- [x] Búsqueda en cadena viva (`search_store_products`) y alta de producto al catálogo (`add_product_from_store`) verificadas (T9b) — Jumbo live: "quinoa" → 3 resultados con PPUM; alta con `dry_run=true` → preview (`vincular`, pack 250 g) sin escribir (catálogo sigue en 102 productos y el match no cambia)
- [x] **Revisión humana antes de Fase 2** — ✔ 2026-11-18: revisión delegada al agente a pedido del usuario, con evidencia e2e contra el contenedor reconstruido (ver ítems anteriores)

---

## Fase 2 — Núcleo completo vía API/MCP (auth §3.1 + flujo canónico §2.2)

### Task 10: CRUD de recetas + create_recipe (dry_run) + rate_recipe
**Descripción:** Subida de recetas propias del usuario: API y MCP para crear/editar recetas con ingredientes estructurados (→`product_id`), **instrucciones de preparación** (texto Markdown y pasos ordenados con duración), tags; `create_recipe` con `dry_run=true` por defecto (preview sin escribir); calificación 1–5 para el futuro aprendizaje de gustos.
**Criterios de aceptación:**
- [x] Alta vía API con ingredientes, pasos y tags; validación: todo ingrediente resuelve al catálogo
- [x] `create_recipe` MCP con `dry_run=true` devuelve preview sin tocar BD; con `false` crea y devuelve `recipe_id`
- [x] `rate_recipe` guarda rating y devuelve promedio
**Verificación:** `pytest backend/tests -k recipes_crud`; llamada MCP dry_run desde inspector. ✔ Verificado 2026-11-18: 7 tests (CRUD completo por API con instrucciones Markdown + pasos con duración, dry_run sin escritura, ingrediente desconocido con sugerencias, alias "aguacate"→palta, kg→g, unidad incompatible, semilla de solo lectura, rating reemplaza/promedia/valida 1-5, tools MCP create_recipe/rate_recipe/get_recipe). API: `GET/POST /api/v1/recipes`, `GET/PUT/DELETE /api/v1/recipes/{id}`, `POST /api/v1/recipes/{id}/ratings`. Con `AUTH_MODE=none` las escrituras se atribuyen a un owner local implícito (`services/identidad.py`), que T13 reemplaza. Inspector MCP manual: pendiente del usuario.
**Dependencias:** T4. **Tamaño:** M
**Archivos:** `backend/app/services/recipes.py`, `backend/app/api/recipes.py`, `backend/app/mcp/tools_recipes.py`

### Task 11: Búsqueda con filtros + escalado + costo por porción
**Descripción:** `search_recipes` (query, tags AND, `max_cost_per_serving`, `max_time_minutes`), `scale_recipe` con reglas Anexo A (huevos ceil, peso/volumen 1 decimal), `get_recipe_cost` vía PriceService. (`only_with_pantry_match` se completa en T19.)
**Criterios de aceptación:**
- [x] Búsqueda filtra por costo con precios de la semilla manual; orden por costo/rating
- [x] `scale_recipe(2 porciones→5)` respeta reglas de redondeo (caso huevo probado)
- [x] `get_recipe_cost` expone desglose por ingrediente con metadatos de precio
**Verificación:** `pytest backend/tests -k search_scale_cost`. ✔ Verificado 2026-11-18: 4 tests nuevos (66 totales). Filtros combinables por costo/tiempo con orden `title|cost|rating` (las recetas con precios incompletos quedan fuera del filtro de costo y al final del orden por costo); `scale_recipe` aplica ceil a `unidad` (huevo 3→3.75→4; semilla Empanadas 12→5: 1.25→2) y 1 decimal a g/ml; `get_recipe_cost` usa el último precio por ingrediente en una sola consulta (`get_latest_prices`), calcula con PPUM (`g→CLP/kg`, `ml→CLP/L`, `unidad→CLP/unidad`) y expone `source`/`confidence`/`fetched_at`/`is_stale` por línea, con `is_complete`+`warning` si falta algún precio. La semilla no trae precios: los tests registran precios manuales y el e2e usó live+manual reales. Endpoints nuevos: `GET /api/v1/recipes/{id}/scale`, `GET /api/v1/recipes/{id}/cost`; tools MCP `scale_recipe` y `get_recipe_cost`. E2E en contenedor reconstruido: Charquicán → $10.517 total ($2.629/porción), 5 líneas live Jumbo + 5 manuales, todas con metadatos.
**Dependencias:** T7, T10. **Tamaño:** M
**Archivos:** `backend/app/services/recipes.py`, `backend/app/services/units.py`, `backend/app/services/prices.py`, `backend/app/api/recipes.py`, `backend/app/mcp/tools_recipes.py`, `backend/tests/test_search_scale_cost.py`

### Task 12: Importación de recetas desde URL (JSON-LD)
**Descripción:** `recipe-scrapers` para importar desde URL creando `recipe_import_jobs`; `import_recipe` MCP con `dry_run`; mapeo best-effort de ingredientes al catálogo por alias con marcado de no-resueltos.
**Criterios de aceptación:**
- [x] Importar 2 recetas reales con JSON-LD → receta draft con ingredientes estructurados
- [x] Ingredientes no mapeados quedan marcados explícitamente (no se pierden)
- [x] Job registra estado, resultado y error por URL inválida
**Verificación:** `pytest backend/tests -k import` ✔ Verificado 2026-11-19: 7 tests nuevos (73 totales) y `ruff check` limpio. `import_recipe` (MCP) y `POST /api/v1/recipes/imports` (REST) comparten `app/services/imports.py`: descarga con timeout 20 s/límite 5 MB → `recipe-scrapers` en modo genérico (`supported_only=False`, acepta JSON-LD de cualquier sitio) → mapeo por nombre/alias tolerando plurales ("papas"→`papa`) y variantes con sustantivo inicial ("aceite de girasol"→`aceite`) → conversión Anexo A (`kg`/`cucharada`/`taza`/`cdta`…). Los no mapeados vuelven en `unresolved[{text,reason,suggestions}]` y el job los conserva; con `dry_run=false` siempre queda job `completed` (con `result_json`) o `failed` (URL inválida, página sin JSON-LD, nada mapeable). E2E en contenedor reconstruido con la dependencia nueva: 2 URLs reales verificadas — `recetas.elperiodico.com/receta-de-lentejas-a-la-jardinera-56889.html` → receta id 15 con 5 ingredientes estructurados (job id 1 `completed`, 7 no resueltos conservados) y `recetasgratis.net/receta-de-charquican-59075.html` (sirve "Bizcocho de yogur sin azúcar") → vista previa con harina/huevo/aceite (3 resueltos, 5 no resueltos). El usuario no fijó una URL concreta, así que se usaron estas dos públicas.
**Dependencias:** T10. **Tamaño:** M
**Archivos:** `backend/app/services/imports.py`, `backend/app/api/recipes.py`, `backend/app/mcp/tools_recipes.py`, `backend/tests/test_imports.py`, `backend/tests/fixtures/receta_charquican.html`, `backend/tests/fixtures/receta_tortilla.html`

### Task 13: Autenticación local multi-usuario (AUTH_MODE dual)
**Descripción:** Registro local (email + contraseña Argon2id) con **aviso de privacidad y consentimiento afirmativo** (Ley 21.719: checkbox no premarcado); login que emite Bearer (hasheado en `api_tokens`); `AUTH_MODE=none|local` — con `none`, owner implícito del hogar por defecto; endpoint `/api/v1/auth/{register,login,me}`.
**Criterios de aceptación:**
- [ ] `AUTH_MODE=none`: sin login, toda la API opera como owner del hogar por defecto
- [ ] `AUTH_MODE=local`: registro exige consentimiento activo; login devuelve Bearer; contraseñas nunca en claro (Argon2id verificado en test)
- [ ] Accesos sin token en modo `local` → 401; tests cubren ambos modos
**Verificación:** `pytest backend/tests -k auth`.
**Dependencias:** T3. (Paralelizable con T7–T12.) **Tamaño:** M
**Archivos:** `backend/app/services/auth.py`, `backend/app/api/auth.py`, `backend/tests/test_auth.py`

### Task 14: Hogares, miembros, roles, invitaciones y supresión
**Descripción:** CRUD de hogares; al registrarse se crea hogar propio (owner) o se une con código de invitación (alfanumérico, un solo uso, 24 h); roles owner/member/viewer con aplicación real de permisos; `update_household_preferences` MCP (owner/member); borrado de hogar en cascada (derecho de supresión Ley 21.719).
**Criterios de aceptación:**
- [ ] Registro → hogar propio con rol owner; unirse con código válido → member; código inválido/expirado/consumido rechazado con error específico
- [ ] viewer no puede escribir preferencias ni recetas; member sí; owner todo (tests por rol)
- [ ] `DELETE /households/{id}` elimina hogar y todos sus datos asociados (recetas, planes, listas, gastos) — test de cascada
**Verificación:** `pytest backend/tests -k households`.
**Dependencias:** T13. (Paralelizable con T7–T12.) **Tamaño:** M
**Archivos:** `backend/app/services/households.py`, `backend/app/api/households.py`, `backend/app/mcp/tools_household.py`, `backend/tests/test_households.py`

### Task 15: Tokens de API + scopes + permisos MCP por rol
**Descripción:** `api_tokens` (hash, scopes `read|write_draft|confirm|admin`, display-once) ligados al usuario autenticado; endpoint + CLI `python -m app.create_token`; mapeo rol→permisos MCP: viewer (lectura), member (draft), owner+token (confirmar/registrar).
**Criterios de aceptación:**
- [ ] Token creado vía CLI/endpoint autentica `Authorization: Bearer` y queda hasheado
- [ ] `confirm_meal_plan` rechazada sin scope `confirm`; tools de lectura aceptan scope `read`
- [ ] El rol del usuario (T14) se refleja en los permisos MCP de todas las tools
**Verificación:** `pytest backend/tests -k tokens`; probar reject/accept por scope y rol.
**Dependencias:** T13, T14. **Tamaño:** M
**Archivos:** `backend/app/services/auth.py`, `backend/app/api/tokens.py`, `backend/app/mcp/permissions.py`

### Task 16: Planificador: draft + entradas + estimación por cadena
**Descripción:** `meal_plans` (unique hogar+semana), `set_meal_plan_entry` (slots desayuno/almuerzo/cena/snack, `servings_multiplier`), `estimate_meal_plan_cost(plan_id, store_ids[])` agregando en unidad canónica vía PriceService, guardando `budget_snapshots`; `get_budget_status`.
**Criterios de aceptación:**
- [ ] Crear plan draft y agregar entradas; una semana → un plan (unique verificado)
- [ ] Estimación devuelve total por cadena + desglose, y persiste snapshot con `fetched_at`
- [ ] `get_budget_status` expone `budget_clp`, `estimated_clp`, `variance_clp`
**Verificación:** `pytest backend/tests -k meal_plan`.
**Dependencias:** T7, T9, T11. **Tamaño:** M
**Archivos:** `backend/app/services/planner.py`, `backend/app/api/plans.py`, `backend/app/mcp/tools_plans.py`

### Task 17: Presupuesto estricto + confirmación con token + noche libre
**Descripción:** Sugeridor que arma la semana dentro de `budget_clp` con variedad (sin repetir receta en 4 semanas configurable); `confirm_meal_plan` requiere token (scope `confirm`) → status confirmed + `confirmed_at`; slot "noche libre" (sobras/llevar) contabilizado con monto estimado configurable.
**Criterios de aceptación:**
- [ ] Plan sugerido respeta presupuesto con recetas del seed y sin repetir dentro de la ventana
- [ ] Confirmar sin token → error; con token → confirmed y congela ediciones draft
- [ ] Noche libre descuenta del presupuesto con monto estimado explícito
**Verificación:** `pytest backend/tests -k budget_confirm`.
**Dependencias:** T15, T16. **Tamaño:** M
**Archivos:** `backend/app/services/planner.py`, `backend/app/mcp/tools_plans.py`, `backend/tests/test_planner.py`

### Task 18: Intercambio de comidas + reequilibrio automático
**Descripción:** `swap_meal(plan_id, entry_id, new_recipe_id)`: reemplaza y reequilibra el resto de la semana para volver al presupuesto, devolviendo ahorro/exceso por swap; la UI mostrará estos valores en T26.
**Criterios de aceptación:**
- [ ] Swap que excede presupuesto dispara reequilibrio documentado (qué cambió y por qué)
- [ ] Retorno incluye costo del nuevo entry, costo nuevo del plan y delta vs presupuesto
- [ ] No-repetición (4 semanas) se mantiene tras reequilibrio
**Verificación:** `pytest backend/tests -k swap_rebalance`; escenario swap caro→reequilibra.
**Dependencias:** T17. **Tamaño:** M
**Archivos:** `backend/app/services/planner.py`, `backend/app/mcp/tools_plans.py`

### Task 19: Despensa: ítems, movimientos, shortfall + vencimientos
**Descripción:** CRUD pantry (ubicación refri/congelador/alacena/otro), `pantry_movements` por cada delta con reason (`purchase|recipe_consumption|manual_adjustment|spoilage`), `get_pantry_shortfall`, alertas `get_pantry_status(expiring_within_days)`; completa `only_with_pantry_match` en `search_recipes`.
**Criterios de aceptación:**
- [ ] Ajustar cantidad genera movimiento con delta y reason; historial consultable
- [ ] `get_pantry_shortfall` calcula faltante para ingredientes requeridos
- [ ] Ítems a vencer en N días aparecen en status; `only_with_pantry_match` filtra correctamente
**Verificación:** `pytest backend/tests -k pantry`.
**Dependencias:** T4 (paralelizable con T16–T18; requerida por T20). **Tamaño:** M
**Archivos:** `backend/app/services/pantry.py`, `backend/app/api/pantry.py`, `backend/app/mcp/tools_pantry.py`

### Task 20: Lista de compras: generación, pasillos, exportación
**Descripción:** `generate_shopping_list(plan_id, store_ids[])`: agrega ingredientes en canónica, **descuenta despensa**, convierte a packs `ceil(q/purchase_size)` (Anexo A), agrupa por categoría/pasillo, ítems manuales, exportación CSV/texto, `get_shopping_list(group_by)`, `update_shopping_list_item` (checked, precio real por ítem).
**Criterios de aceptación:**
- [ ] Lista desde plan semilla: sin duplicados, despensa descontada, packs correctos (caso pasta 700 g → 1 pack 1 kg)
- [ ] Agrupación por pasillo configurable por hogar; ítem manual agregable
- [ ] CSV exportable y `group_by=aisle|store` funciona
**Verificación:** `pytest backend/tests -k shopping_list`; generar lista real del plan del checkpoint C.
**Dependencias:** T16, T19. **Tamaño:** L → dividir generación/agrupación-export si crece.
**Archivos:** `backend/app/services/shopping.py`, `backend/app/api/lists.py`, `backend/app/mcp/tools_lists.py`

### Task 21: Comparación entre cadenas + dividir la compra
**Descripción:** `compare_basket_across_stores(list_id)`: total por cadena comparando por **PPUM** cuando difieren formatos, marca ítems donde una cadena es más barata y sugiere "dividir la compra" si el ahorro supera umbral configurable del hogar.
**Criterios de aceptación:**
- [ ] Comparación usa PPUM (no precio absoluto) cuando hay formatos distintos
- [ ] Sugerencia de división solo supera el umbral (default: p.ej. 10%, configurable)
- [ ] Cadena caída no rompe la comparación (reporte parcial, como upstream)
**Verificación:** `pytest backend/tests -k compare`; comparación real Jumbo vs Santa Isabel con lista del seed.
**Dependencias:** T9, T20. **Tamaño:** M
**Archivos:** `backend/app/services/comparison.py`, `backend/app/mcp/tools_lists.py`

### Task 22: Gastos reales + varianza + resúmenes
**Descripción:** `record_expense` (amount, store, items opcionales, token requerido) → `expenses`/`expense_items`; `get_budget_variance(period)`, `get_spending_summary(group_by=category|store)`; categorías sembradas.
**Criterios de aceptación:**
- [ ] Registro de gasto crea expense + items y cierra el ciclo presupuestario de la semana
- [ ] Varianza compara presupuestado vs real del período; resumen agrupa por categoría/cadena
- [ ] `record_actual_purchase` (variante desde lista) requiere token
**Verificación:** `pytest backend/tests -k expenses`; flujo manual semana completa: estimar → confirmar → lista → gasto real → varianza.
**Dependencias:** T15, T16. **Tamaño:** M
**Archivos:** `backend/app/services/expenses.py`, `backend/app/api/expenses.py`, `backend/app/mcp/tools_expenses.py`

### Task 23: MCP HTTP (streamable) + prompts + resources completos
**Descripción:** Transporte HTTP con token Bearer (para agentes en red local), los 4 resources (`household://`, `meal-plan://`, `shopping-list://`, `pantry://`) y los 3 prompts (`plan_week_within_budget`, `suggest_meals_from_pantry`, `compare_current_basket`); `docs/mcp-tools.md` completo con permisos por rol.
**Criterios de aceptación:**
- [ ] Servidor MCP arranca en stdio y en HTTP según `MCP_TRANSPORT`
- [ ] HTTP exige Bearer token con scope válido
- [ ] Los 3 prompts devuelven plantillas correctas con datos del hogar
**Verificación:** `pytest backend/tests -k mcp_http`; inspector MCP sobre HTTP con token.
**Dependencias:** T15, T22. **Tamaño:** M
**Archivos:** `backend/app/mcp_server.py`, `backend/app/mcp/prompts.py`, `docs/mcp-tools.md`

### ✅ Checkpoint C — Flujo canónico §2.2 100% vía MCP
- [ ] Un agente ejecuta: `get_household_context` → `search_recipes` → `create_meal_plan` → `estimate_meal_plan_cost` → **confirmación humana con token** → `generate_shopping_list` → `compare_basket_across_stores` → `record_actual_purchase`, sin tocar la web
- [ ] Toda tool de escritura respeta `dry_run`, las reglas de token (T15) y el rol del usuario autenticado (T14)
- [ ] **Revisión humana antes de Fase 3**

---

## Fase 3 — Interfaz web SvelteKit (PWA) (spec §3.10)

### Task 24: SvelteKit scaffold + cliente API + StaticFiles + PWA base
**Descripción:** SvelteKit estático, cliente tipado contra OpenAPI de FastAPI, servido por FastAPI (StaticFiles) en el mismo contenedor; `manifest.json`, shell responsive en español chileno, rutas `/login` y `/registro` operativas con `AUTH_MODE=local` (consentimiento Ley 21.719) y bypass con `AUTH_MODE=none`; job de CI para `npm run check`+`build`.
**Criterios de aceptación:**
- [ ] `docker compose --profile minimal up` sirve la web en `/` junto a `/docs`
- [ ] Cliente API tipado regenerable desde OpenAPI; CI frontend verde
- [ ] Registro/login funcionales en modo `local`; en modo `none` redirigen al dashboard
- [ ] Manifest instalable (nombre, iconos, theme)
**Verificación:** `npm run check` + `npm run build`; abrir `/` desde compose y registrar un usuario.
**Dependencias:** T2, T13. **Tamaño:** M
**Archivos:** `frontend/`, `backend/app/main.py` (StaticFiles), `.github/workflows/ci.yml`

### Task 25: Recetario (búsqueda, tarjetas, detalle, calificación)
**Descripción:** Vista de búsqueda con filtros y tarjetas (costo estimado + rating), detalle con ingredientes escalables (porciones ajustables) y pasos; calificar 1–5.
**Criterios de aceptación:**
- [ ] Filtros de T11 operables desde la UI; costo visible por tarjeta con metadatos de precio
- [ ] Ajuste de porciones recalcula cantidades con las reglas Anexo A
- [ ] Rating persiste y actualiza promedio
**Verificación:** `npm run check`; manual: buscar "cazuela", escalar a 6 porciones, calificar.
**Dependencias:** T11, T24. **Tamaño:** M
**Archivos:** `frontend/src/routes/recipes/`

### Task 26: Planificador semanal UI
**Descripción:** Calendario semanal con drag&drop, barra de presupuesto (dentro/excedido), botón "reequilibrar", swap con indicador de ahorro/exceso, confirmación (usa token), noche libre.
**Criterios de aceptación:**
- [ ] Crear/ver/editar plan draft; costo total visible en vivo al cambiar entradas
- [ ] Swap desde la UI muestra delta y dispara reequilibrio (T18)
- [ ] Confirmar pide token (link a /settings/tokens) y congela el plan
**Verificación:** `npm run check`; manual: armar semana del seed dentro de presupuesto y confirmar.
**Dependencias:** T17, T18, T24. **Tamaño:** L → dividir en (a) calendario+barras, (b) swap/reequilibrio+confirmación si crece.
**Archivos:** `frontend/src/routes/planner/`, `frontend/src/lib/api/plans.ts`

### Task 27: Lista de compras UI + offline básico
**Descripción:** Ítems por pasillo con checkboxes, comparación por cadena (tabla PPUM), exportar CSV/texto, precio real por ítem al marcar; service worker mínimo: la lista activa cacheada y legible sin conexión.
**Criterios de aceptación:**
- [ ] Marcar ítems persiste y sincroniza al reconectar; lista agrupada por pasillos del hogar
- [ ] Tabla de comparación Jumbo/Santa Isabel visible con fuente/fecha de precio
- [ ] Con red cortada, la lista activa sigue visible (SW cachea la ruta)
**Verificación:** `npm run check`; manual DevTools offline: lista visible y checkeable localmente.
**Dependencias:** T20, T21, T24. **Tamaño:** M
**Archivos:** `frontend/src/routes/list/`, `frontend/src/service-worker.ts`

### Task 28: Modo Cocina
**Descripción:** Pantalla completa con pasos grandes, temporizadores por paso (`duration_minutes`), wake-lock (pantalla siempre activa), navegación anterior/siguiente.
**Criterios de aceptación:**
- [ ] Modo cocina desde detalle de receta: pasos grandes + timer con alarma
- [ ] Wake-lock activo en navegadores compatibles (degrada sin error)
- [ ] Navegación por pasos sin perder timer en curso
**Verificación:** `npm run check`; manual: cocinar receta del seed con timer activo.
**Dependencias:** T25. **Tamaño:** M
**Archivos:** `frontend/src/routes/recipes/[id]/cook/`

### Task 29: Dashboard + Inventario UI + Configuración (miembros e invitaciones)
**Descripción:** Dashboard (barra presupuesto, plan actual, lista pendiente, gasto acumulado), inventario con ubicaciones/vencimientos/alertas, configuración (preferencias hogar, supermercados, IA opcional, tokens display-once, **miembros e invitaciones**: generar/copiar código).
**Criterios de aceptación:**
- [ ] Dashboard refleja datos reales del hogar (T22) sin recarga manual excesiva
- [ ] Inventario editable con movimientos visibles y alertas de vencimiento
- [ ] Tokens generados desde UI mostrando valor una sola vez; gestión de miembros con invitaciones operativa (T14)
**Verificación:** `npm run check`; manual: flujo hogar completo desde dashboard + invitar a un segundo usuario.
**Dependencias:** T14, T19, T22, T24. **Tamaño:** L → dividir dashboard/inventario y configuración si crece.
**Archivos:** `frontend/src/routes/`, `frontend/src/routes/settings/`

### Task 30: Home Assistant Nivel 1 (sensores REST) + docs
**Descripción:** Endpoints estables `/api/v1/households/{id}/dashboard` y `/api/v1/shopping-lists/active` con Bearer; `docs/home-assistant.md` con YAML de `rest` sensors y `rest_command` (spec §4.1).
**Criterios de aceptación:**
- [ ] Ambos endpoints responden JSON estable documentado con token de solo lectura
- [ ] YAML de ejemplo válido para `configuration.yaml` de HA
- [ ] Docs incluyen aviso de red local y creación del token read-only
**Verificación:** curl con token read-only; docs revisadas.
**Dependencias:** T15, T16, T20. **Tamaño:** S
**Archivos:** `backend/app/api/ha.py`, `docs/home-assistant.md`

### ✅ Checkpoint D — MVP humano completo (criterio Fase 1 spec)
- [ ] Un hogar planifica una semana, genera la lista, compra y registra el gasto **sin tocar la BD a mano** (todo por la web)
- [ ] Registro/login/invitación operativos con `AUTH_MODE=local` (dos usuarios en un hogar probados)
- [ ] PWA instalable; lista offline; modo cocina operativo
- [ ] Sensores REST de HA funcionando con ejemplo YAML
- [ ] **Revisión humana antes de Fase 4**

---

## Fase 4 — v1: IA opcional, MQTT, importaciones, release (spec Fase 2)

### Task 31: Adaptador de IA OpenAI-compatible
**Descripción:** `ai/adapter.py` con `AI_PROVIDER`/`AI_API_KEY`/`AI_MODEL`/`AI_BASE_URL` solo desde `.env` (nunca BD); funciones opcionales: estructurar receta desde texto pegado (reusa `recipe_import_jobs`), sugerencias de recetas desde despensa; sistema 100% funcional con `AI_PROVIDER=none`.
**Criterios de aceptación:**
- [ ] Con `AI_PROVIDER=none`, importación por texto devuelve error accionable sin romper nada
- [ ] Con proveedor configurado: texto pegado → receta draft con ingredientes mapeados al catálogo
- [ ] Ningún dato de precios/credenciales/gastos se envía a la IA (test de payload)
**Verificación:** `pytest backend/tests -k ai_adapter`; manual con clave de prueba del usuario.
**Dependencias:** T12. **Tamaño:** M
**Archivos:** `backend/app/ai/adapter.py`, `backend/app/services/imports.py`, `.env.example`

### Task 32: MQTT Nivel 2 con descubrimiento automático
**Descripción:** `mqtt/publisher.py` (paho-mqtt) publica `marketsano/{household_id}/...` y mensajes de discovery HA (spec §4.2) al cambiar estado; servicio `mqtt` en perfil `full` con Mosquitto.
**Criterios de aceptación:**
- [ ] Al confirmar plan/marcar ítem/registrar gasto, los topics se actualizan
- [ ] Discovery crea sensores en HA sin configuración manual (device con 4 sensores)
- [ ] `MQTT_ENABLED=false` → módulo inactivo y sin errores
**Verificación:** `pytest backend/tests -k mqtt`; manual con Mosquitto + mosquito_sub.
**Dependencias:** T16, T20, T22. **Tamaño:** M
**Archivos:** `backend/app/mqtt/publisher.py`, `docker-compose.yml`, `docs/home-assistant.md`

### Task 33: Importación Mealie/Tandoor + exportación + backups
**Descripción:** Import desde export JSON de Mealie (mapeo name/recipeIngredient/recipeInstructions/categories) reutilizable para Tandoor; exportación completa JSON/CSV; backup diario a volumen `./backups` (cron/job).
**Criterios de aceptación:**
- [ ] Export Mealie de prueba importa recetas con ingredientes al catálogo (best-effort + marcados)
- [ ] Exportación JSON contiene todas las tablas del hogar; CSV de gastos por período
- [ ] Backup programado rota archivos y es restaurable
**Verificación:** `pytest backend/tests -k import_mealie`; restaurar backup en BD limpia.
**Dependencias:** T12. **Tamaño:** M
**Archivos:** `backend/app/services/imports.py`, `backend/app/services/backup.py`, `docker-compose.yml`

### Task 34: Imágenes multi-arch GHCR + release v0.1.0
**Descripción:** Buildx amd64/arm64 a GHCR (o registro decidido — ver pregunta abierta), workflows de release, perfiles minimal/standard/full documentados en README, changelog, tag `v0.1.0`, `docs/mcp-tools.md` final como referencia de API MCP.
**Criterios de aceptación:**
- [ ] Imagen multi-arch publicada y `docker compose up` funcional desde imagen (no solo build local)
- [ ] Release en GitHub con notas; README documenta los 3 perfiles y requisitos del conector
- [ ] Criterio de salida spec Fase 2: flujo agente completo con precios reales de ≥2 cadenas
**Verificación:** Clonar en máquina limpia y levantar perfil `standard` desde imagen publicada.
**Dependencias:** T9, T23, T30–T33. **Tamaño:** M
**Archivos:** `.github/workflows/release.yml`, `README.md`, `CHANGELOG.md`

### ✅ Checkpoint E — v1 publicada
- [ ] Release público v0.1.0 con imágenes multi-arch
- [ ] Agente ejecuta el flujo completo con Jumbo + Santa Isabel (o Unimarc) reales
- [ ] IA opcional demostrada con proveedor del usuario; sin IA todo sigue funcional
- [ ] **Revisión humana para decidir Fase 5**

---

## Fase 5 — v2 ecosistema (futuro: re-descomponer al llegar)

Sin descomponer todavía (lista "sobra"/v2 de spec §9.2 y §8 F3):

- [ ] Importación de recetas desde video (transcripción + IA)
- [ ] OCR de recibos
- [ ] Browser-bridge para **Líder/Tottus** (puente de navegador del upstream)
- [ ] Custom Component HA (Nivel 3) + Add-on HAOS + HACS
- [ ] OIDC (Authelia/Keycloak) + refinamientos Ley 21.719 (portabilidad de datos)
- [ ] PWA offline completo
- [ ] Plugins de conectores para otros países
- [ ] Re-evaluación FastMCP 3.x/4.x

---

## Notas de dependencias (paralelización)

- **Seguras en paralelo:** T6 (CI) con T3–T5; T13–T14 (auth/hogares) con T7–T12 (solo requieren T3); T19 (despensa) con T16–T18; vistas de Fase 3 (T25/T27/T28) entre sí una vez que T24 existe.
- **Estrictamente secuenciales:** T2→T3→T4 (esquema→semilla); T7→T8→T9 (contrato→spike→integración); T13→T14→T15 (auth→hogares→tokens); T16→T17→T18 (plan→confirm→swap).
- **Puertas de decisión:** T8 — si el spike falla, se replanifica la integración de precios (adaptador propio) antes de T9.
