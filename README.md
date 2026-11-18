<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# 🥘 Market Sano

> Planifica tus comidas con tu presupuesto y los **precios reales** de los supermercados chilenos. Local-first, open-source y MCP-first.

[![Licencia: GPL-3.0-or-later](https://img.shields.io/badge/licencia-GPL--3.0--or--later-blue.svg)](LICENSE)

**Market Sano** (antes *Rinde La Olla*) es un planificador semanal de comidas y compras para Chile que corrige lo que las apps comerciales ignoran deliberadamente: **los precios que ves son los precios que pagas en caja**, y tus datos son tuyos.

## ✨ Qué ofrece

| | |
|---|---|
| 💸 **Presupuesto como eje** | El plan semanal se arma alrededor de tu presupuesto en CLP; si una comida no cabe, la semana se reequilibra automáticamente. |
| 🛒 **Precios reales, no estimados** | Conector 100% local para Jumbo, Santa Isabel y Unimarc (Líder/Tottus en camino) con trazabilidad: cada precio indica origen (`live`/`cached`/`manual`), fecha de consulta y nivel de confianza. |
| 🏠 **Despensa inteligente** | Lo que ya tienes en casa se descuenta del costo y de la lista de compras. Alertas de vencimiento. |
| 📋 **Lista por pasillo + comparación** | Agrupada por categoría y exportable; compara tu carro entre cadenas por **PPUM** (precio por unidad de medida, exigencia SERNAC). |
| 🤖 **MCP-first** | Toda la lógica es operable por agentes (Claude Desktop, Cursor, tu propio bot) vía tools, resources y prompts MCP, sin depender de la interfaz web. |
| 🍳 **Modo Cocina** | Pasos grandes, temporizadores integrados y pantalla que no se apaga. |
| 🔒 **Privacidad por defecto** | Sin telemetría, sin tracking, sin SDKs de analítica. Tus claves y datos nunca salen de tu máquina. Cumplimiento de la Ley 21.719 por diseño. |
| 🏠 **Home Assistant** | Sensores REST desde el MVP; MQTT Discovery y custom component en el roadmap. |
| 🧠 **IA opcional y agnóstica** | Conecta tu propio proveedor (OpenRouter, Anthropic, Gemini, DeepSeek)… o no conectes ninguna: el sistema es 100% funcional sin IA. |
| 🆓 **100% gratuito y open-source** | GPL-3.0-or-later. Sin cuentas en la nube, sin paywall, sin "plan premium". |

## 🚀 Quickstart

Requisitos: Docker (con compose v2).

```bash
git clone https://github.com/danielsalinasgongora/market-sano.git
cd market-sano
cp .env.example .env
docker compose up
```

- API + documentación OpenAPI: <http://localhost:8000/docs>
- Perfiles: `--profile standard` añade PostgreSQL 16 · `--profile full` añade MQTT (Home Assistant) y el conector de supermercados.

> ⚠️ **Estado actual: Fase 0 (esqueleto) en curso.** El quickstart completo será funcional al cierre de la Fase 0. Progreso y hoja de ruta en [`tasks/todo.md`](tasks/todo.md); diseño completo en [`docs/spec.md`](docs/spec.md).

## 🤖 Operarlo con un agente (MCP)

El backend expone tools MCP (`get_household_context`, `search_recipes`, `create_meal_plan`, `estimate_meal_plan_cost`, `generate_shopping_list`, `compare_basket_across_stores`, …) con reglas de seguridad claras: un agente puede armar y estimar planes en borrador, pero **confirmar un plan o registrar un gasto real exige un token emitido por un humano**.

Guía de conexión con Claude Desktop: [`docs/clients/claude-desktop.md`](docs/clients/claude-desktop.md) *(se publica durante la Fase 0)*.

## 🗺️ Roadmap

| Fase | Entrega |
|---|---|
| **0** | Esqueleto público: Docker, modelo de datos, semilla chilena, MCP de lectura. |
| **1** | Precios reales temprano: contrato de precios con trazabilidad + conector Jumbo/Santa Isabel/Unimarc. |
| **2** | Núcleo vía MCP: recetas → plan → despensa → lista → gastos (flujo canónico completo por agente). |
| **3** | Web PWA completa (recetario, planificador, lista offline, modo cocina, dashboard). |
| **4** | v1: IA opcional, MQTT Discovery, importadores Mealie/Tandoor, imágenes multi-arch. |
| **5** | v2: video, OCR, Líder/Tottus (puente de navegador), custom component HA. |

## 🤝 Contribuir

Lee [CONTRIBUTING.md](CONTRIBUTING.md) — el proyecto se rige por el [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Las contribuciones más útiles hoy: recetas chilenas para la semilla, productos del catálogo con alias regionales, y buenos reportes de issues.

## 📄 Licencia

**GPL-3.0-or-later** — ver [LICENSE](LICENSE). La spec v2.0 propuso originalmente AGPL-3.0; el mantenedor decidió GPL-3.0-or-later (decisión registrada en `docs/spec.md` §9.1).

Créditos: la comparativa de producto (TapCook, Piatto) está documentada en la spec. Los precios reales son posibles gracias a [`mcp-supermercados-cl`](https://github.com/NLACE-COM/mcp-supermercados-cl) (MIT), que se ejecuta 100% en tu máquina.
