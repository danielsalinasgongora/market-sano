<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Contribuir a Market Sano

¡Gracias por tu interés! Market Sano es un proyecto comunitario chileno, 100% open-source (GPL-3.0-or-later).

## Estado del proyecto

Estamos en **Fase 0** (esqueleto y validación técnica). Las contribuciones más útiles ahora mismo:

- 🍲 **Recetas chilenas estructuradas** para la semilla de datos (cazuela, charquicán, pastel de choclo, porotos con riendas, …). El formato se define en `backend/app/seed_data/` durante la Fase 0.
- 🛒 **Productos del catálogo** con alias regionales ("palta"/"aguacate", "poroto"/"frijol", "zapallo italiano", …).
- 🐛 **Issues con contexto**: pasos de reproducción, entorno (host Docker / HA / cliente MCP).
- 📖 **Mejoras a la spec** (`docs/spec.md`) vía PR de discusión.

## Reglas del repo

1. **Idioma:** UI y documentación en **español chileno**; identificadores de código en inglés. "Palta", no "aguacate".
2. **Licencia de contribuciones:** todo aporte se publica bajo **GPL-3.0-or-later**. Al enviar un PR confirmas que tienes derecho a licenciar tu aporte bajo esos términos.
3. **Commits:** mensaje en español con tipo convencional (`feat:`, `fix:`, `docs:`, `test:`, `chore:`), idealmente una tarea del plan (`tasks/todo.md`) por commit.
4. **Calidad:** `ruff check` y `pytest` deben pasar antes de cada push. El CI lo exigirá.
5. **Sin telemetría:** cualquier PR que añada tracking, anuncios o SDKs de analítica será rechazado (principios rectores en `docs/spec.md` §0).
6. **Secretos:** nunca commits de claves o credenciales. Usa `.env.example` como plantilla y `.env` está ignorado.
7. **Trazabilidad de precios:** todo precio que entre al sistema debe llevar `source`, `fetched_at` y `confidence` (spec §0.6).

## Estructura del monorepo

```text
backend/    API FastAPI + SQLModel + Alembic + MCP (FastMCP)
frontend/   SvelteKit (PWA)
docker/     Dockerfiles
docs/       Especificación, guías de conectores, Home Assistant
tasks/      Plan de desarrollo y lista de tareas (roadmap vivo)
```

## Entorno de desarrollo

- Docker + docker compose v2 (flujo principal: `docker compose --profile minimal up`).
- Python 3.12+ para desarrollo local del backend; Node 20+ para el frontend y para el conector `mcp-supermercados-cl`.
- Los detalles de comandos (tests, migraciones, semilla) se completan durante la Fase 0 junto con el esqueleto.

## Código de conducta

Ver [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). En resumen: sé amable, respeta a los demás, y recuerda que esto lo construye gente en su tiempo libre.
