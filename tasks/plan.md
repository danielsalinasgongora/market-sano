# Plan de Implementación — Market Sano

**Fecha:** 2026-11-17 · **Estado:** APROBADO (v1.1 con multi-usuario desde v0.1)
**Fuente:** Especificación Técnica v2.0 (completa, recibida 2026-11-17) + decisiones del usuario en sesión.
**Lista de tareas ejecutable:** `tasks/todo.md`

---

## Resumen

Market Sano (antes *Rinde La Olla*): planificador de comidas local-first, open-source (**GPL-3.0-or-later**) y MCP-first para Chile, con **precios reales** del retail chileno como diferenciador central. Un único `docker compose up` levanta todo: API REST (FastAPI) + servidor MCP (FastMCP) + web PWA (SvelteKit) + SQLite, con Postgres/MQTT/conector de supermercados como perfiles opcionales.

El plan entrega en **v0.1** el vertical mínimo completo: *recetas → plan semanal con presupuesto CLP → lista de compras con precios reales → registro de gasto*, operable íntegramente vía MCP (flujo canónico §2.2 de la spec) y vía web, **con autenticación local multi-usuario** (registro + roles owner/member/viewer + invitaciones) y `AUTH_MODE=none` como modo sin fricción.

---

## Decisiones ya tomadas

### Decidido por el usuario (sesión 2026-11-17)

| # | Decisión | Valor |
|---|----------|-------|
| D1 | **Licencia** | **GPL-3.0-or-later** (sobrescribe el AGPL-3.0 de la spec). Repo **público en GitHub desde la Fase 0**. Dependencias verificadas compatibles: FastMCP (Apache-2.0), mcp-supermercados-cl (MIT), SvelteKit (MIT), recipe-scrapers (MIT). |
| D2 | **Alcance v0.1** | Vertical mínimo completo: recetas → plan → lista, con API REST + MCP + web PWA mínima. |
| D3 | **Precios reales** | Desde el inicio (adelanta el ítem "conectores" de la Fase 2 de la spec a nuestra Fase 1). |
| D4 | **Ubicación del código** | `H:\Mi unidad\DEVELOP\Rinde La Olla` (Google Drive). Ver riesgos. |
| D5 | **Autenticación v0.1** (spec §9.1) | **Multi-usuario local desde v0.1**: registro email + Argon2id, roles owner/member/viewer, invitaciones de un solo uso (24 h). `AUTH_MODE=none` se mantiene como modo sin fricción (hogar por defecto). OIDC se difiere a Fase 5. |
| D6 | **GitHub** | Repo público: https://github.com/danielsalinasgongora/market-sano (creado por el usuario, URL entregada 2026-11-17). El agente configura `origin` y hace el push inicial. |
| D7 | **Nombre del producto** | **Market Sano** (sobrescribe el nombre de la spec v2.0 §9.1, que usaba "Rinde La Olla"). Identificadores técnicos y topics MQTT: `marketsano`. La carpeta local de Drive conserva su nombre; no afecta al repo. |
| D8 | **Catálogo abierto y recetas propias** (2026-11-17) | (1) Los usuarios suben recetas propias con instrucciones de preparación (T10/T12/T31 + web T25). (2) Pueden **buscar artículos en el supermercado** vía conector y darlos de alta como productos/ingredientes: nueva **Task 9b** (tools `search_store_products` + `add_product_from_store`; tabla `product_store_matches`, migración 0002). (3) Esos artículos entran al ciclo de refresco de precios del conector (T9/T9b). Sin menciones a productos de terceros en la documentación pública. |

### Decidido por la spec (adoptado tal cual)

- **Monorepo** según Anexo C, con una desviación: `docker-compose.yml` en la **raíz** (no en `docker/`) para que `docker compose up` funcione sin `-f`.
- **Backend:** Python 3.12 + FastAPI + SQLModel + Alembic; SQLite por defecto, Postgres opcional (perfil `standard`).
- **MCP:** mismo código, distinto entrypoint (`main.py` API / `mcp_server.py` MCP); transporte stdio principal + HTTP streamable secundario. **Pin `fastmcp<3`** (3.0/4.x están en desarrollo con breaking changes; se re-evalúa en Fase 4).
- **Frontend:** SvelteKit compilado a estáticos y servido por FastAPI (StaticFiles); PWA con manifest + service worker mínimo para la lista offline.
- **Autenticación (§3.1, ampliado por D5):** dual desde v0.1 — `AUTH_MODE=none` (sin login, owner implícito del hogar por defecto) y `AUTH_MODE=local` (registro con **aviso de privacidad + consentimiento afirmativo** según Ley 21.719, vigente desde 2026-12-01; contraseñas Argon2id; derecho de supresión con borrado en cascada del hogar).
- **Seguridad MCP:** escrituras en `draft` sin token; `confirm_meal_plan` y `record_actual_purchase` requieren token de confirmación humana; `dry_run=true` por defecto en todas las tools de escritura (propuesta §3.7 adoptada). Roles MCP heredan el rol del usuario autenticado.
- **Unidades (Anexo A):** unidad canónica (g/ml/unidad), packs = `ceil(cantidad / purchase_size)`, discretos (huevos) siempre ceil, peso/volumen con 1 decimal; equivalencias de cocina (cucharada/taza) en tabla estática.
- **Idioma:** UI y datos en español chileno desde el día 1 ("palta", no "aguacate"); identificadores de código en inglés; CLP con PPUM obligatorio (`unit_price_clp`).
- **IA:** adaptador OpenAI-compatible opcional (OpenRouter/Anthropic/Gemini/DeepSeek); claves solo en `.env`, nunca en BD; sistema 100% funcional sin IA.
- **Privacidad:** sin telemetría ni tracking; credenciales de supermercado y claves de IA nunca salen del contenedor; cumplimiento Ley 21.719 por diseño.

### Decidido por investigación (verificado 2026-11-17)

- **Conector:** `NLACE-COM/mcp-supermercados-cl` (MIT, v1.4.9, pruebas semanales contra webs reales) se integra **como cliente MCP vía stdio** (subproceso local que el backend lanza y al que habla por MCP), no reimplementando adaptadores.
- **Cadenas realistas v0.1:** **Jumbo, Santa Isabel y Unimarc** responden a fetch directo (verificado incluso desde GitHub Actions). **Líder y Tottus bloquean por fingerprint del cliente (PerimeterX/F5)**, no por IP: requieren puente de navegador del usuario → se difieren a Fase 5. La spec menciona "Jumbo y Líder primero": el plan sustituye Líder por Santa Isabel/Unimarc como segundas cadenas y documenta el porqué.
- **Ventaja adicional del conector:** ya entrega `unitPrice` normalizado (PPUM) y `memberPrice` (Jumbo Prime) → alimenta directamente los requisitos PPUM (SERNAC) y el campo `price_club`.

---

## Mapeo con el roadmap de la spec (§8)

La spec pone precios reales en su Fase 2 (sem. 12–23). Por la decisión D3, **nuestra Fase 1 adelanta la capa de precios + conector**. Por D5, la Fase 2 incorpora el módulo de Hogar/Autenticación §3.1. El resto conserva el orden y los criterios de salida de la spec:

| Nuestra fase | Contenido | Equivalente spec §8 |
|---|---|---|
| Fase 0 — Esqueleto público | Repo GPL-3.0, Docker minimal, esquema completo, semilla, MCP lectura, CI | Fase 0 (sem. 1–3) |
| Fase 1 — Precios temprano | Contrato de precios con trazabilidad + spike + integración conector + **catálogo abierto (T9b, decisión D8)** | (adelanto de Fase 2) |
| Fase 2 — Núcleo vía API/MCP | Autenticación/hogares §3.1 + recetas → plan → despensa → lista → gasto, con tools MCP de escritura | Fase 1 (sem. 4–11) + MCP de Fase 2 |
| Fase 3 — Web PWA | Las 7 vistas del MVP (incl. login/registro) + PWA + HA Nivel 1 | Fase 1 (interfaz web) |
| Fase 4 — v1 completo | IA opcional, MQTT Nivel 2, Mealie/Tandoor, multi-arch, release | Fase 2 (sem. 12–23) |
| Fase 5 — v2 ecosistema | Video, OCR, browser-bridge Líder/Tottus, OIDC, HA Nivel 3 | Fase 3 (continuo) |

**Principio de orden interno:** la Fase 2 construye el flujo canónico §2.2 *solo con MCP* (coherente con la filosofía MCP-first de la spec: "sin tocar la interfaz web"); la Fase 3 lo hace humano. Cada tarea es un slice vertical testable de forma independiente.

---

## Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Scraping frágil: las webs cambian sin aviso (Jumbo migró a App Router; ofertas caducan por campaña) | Alto | Conector aislado tras el contrato `PriceService` (`source`/`confidence`/`fetched_at`); degradación elegante live → cache → manual; upstream mantiene pruebas semanales; nuestras cadenas v0.1 son las de fetch directo. |
| Líder/Tottus bloquean por fingerprint, no por IP | Alto (expectativa) | Declarado desde el plan: v0.1 = Jumbo + Santa Isabel + Unimarc; puente de navegador (upstream `browserHtml`) en Fase 5. |
| FastMCP 3.0/4.x en camino con breaking changes | Medio | Pin `fastmcp<3` en Fase 0; re-evaluación planificada en Fase 4. |
| Superficie de autenticación dual (none + local) desde v0.1 | Medio | Argon2id para contraseñas; tokens hasheados con scopes; tests de permisos por rol en T13–T15; consentimiento Ley 21.719 en el registro; borrado en cascada verificado. |
| Desarrollo dentro de Google Drive (node_modules, .venv, SQLite sincronizados) | Medio | `.gitignore` estricto; BD y backups en volúmenes; pedir al usuario excluir `node_modules/`, `.venv/`, `data/`, `backups/` de la sincronización de Drive. |
| Scope creep (la spec es enorme; video, OCR, HACS, etc.) | Alto | Lista "sobra" (spec §9.2) aparcada en Fase 5 sin descomponer; checkpoints con revisión humana entre fases. |
| Ley 21.719 (vigente desde 2026-12-01) y PPUM SERNAC | Medio | Por diseño: sin tracking, minimización (comuna, no dirección), consentimiento afirmativo en registro, borrado en cascada del hogar, `unit_price_clp` obligatorio en todo `price_snapshots`. |
| ToS de supermercados | Medio | El scraping lo ejecuta el proceso local del usuario a ritmo humano (diseño del upstream MIT); el proyecto no opera infraestructura de scraping; riesgo documentado en `docs/legal-privacy.md`. |
| PWA offline: complejidad de service worker | Bajo/Medio | SW mínimo solo para la lista de compras en v0.1; offline completo en Fase 5. |
| SQLModel + Alembic: casos borde en autogenerado | Bajo | Migración baseline explícita en Fase 0; migraciones revisadas manualmente en cada PR. |

---

## Preguntas abiertas

1. **Publicación de imágenes Docker (T34):** se recomienda **GHCR** (gratuito, integrado con el repo público GitHub) — confirmar o indicar Docker Hub.

### Resueltas en sesión (2026-11-17)

- **Autenticación v0.1 (spec §9.1):** multi-usuario local desde el inicio (registro + roles + invitaciones), con `AUTH_MODE=none` disponible como modo sin fricción. → Tareas T13–T14; OIDC diferido a Fase 5.
- **GitHub:** el usuario crea el repo público y entrega la URL; el agente configura `origin` y hace el push inicial (T1).
- **Licencia:** **GPL-3.0-or-later**.

---

## Reglas de ejecución

- Toda tarea termina con `pytest` verde, `ruff check` limpio y la verificación manual de su tarjeta en `tasks/todo.md` antes de marcar `[x]`.
- Commits atómicos por tarea; el español es el idioma de UI/docs, el inglés de identificadores; SPDX `GPL-3.0-or-later` en headers de código.
- Ninguna tarea toca más de ~5 archivos; si crece, se divide (regla del skill de planificación).
- Al final de cada fase hay un checkpoint con revisión humana antes de continuar.
