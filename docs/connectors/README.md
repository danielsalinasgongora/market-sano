# Conector de supermercados

Market Sano obtiene precios en vivo con [`mcp-supermercados-cl`](https://github.com/NLACE-COM/mcp-supermercados-cl) (MIT), un servidor MCP local. El backend lo lanza como **subproceso** y le habla MCP por **stdio**. No hay servidor intermedio: las consultas salen desde tu máquina, a ritmo humano, solo hacia los sitios de las cadenas. Decisión y evidencia: [spike-2026-11.md](spike-2026-11.md).

## Activarlo

| Dónde | Qué hacer |
|---|---|
| Docker (cualquier perfil) | `SUPERMERCADOS_ENABLED=true docker compose up`. La imagen ya trae Node y el conector en `/opt/mcp-supermercados-cl`. |
| Desarrollo local | Instala Node.js ≥ 20 y pon `SUPERMERCADOS_ENABLED=true` en `.env`. Por defecto se lanza con `npx -y mcp-supermercados-cl@1.4.9`; puedes cambiarlo con `SUPERMERCADOS_COMMAND` (lista JSON). |

Requisitos de red: una conexión normal de hogar. Jumbo, Santa Isabel y Unimarc funcionan con fetch directo. **Líder y Tottus** bloquean por antibot y quedan deshabilitados hasta el puente de navegador (Fase 5).

## Cómo funciona

`GET /api/v1/products/{id}/price?store_id=jumbo`:

1. Si hay un precio `live` dentro del TTL (`PRICE_CACHE_TTL_HOURS`, 12 h por defecto), se devuelve sin consultar la cadena.
2. Si no, y el producto tiene **match** para esa cadena (`product_store_matches`), se consulta el conector:
   - Jumbo / Santa Isabel → `get_product(url)` del match.
   - Unimarc → `search_products(nombre)` y se elige el resultado con el `sku` del match.
3. El resultado se guarda como snapshot `source=live, confidence=high`. El PPUM se convierte a la unidad del catálogo (g → CLP/kg, ml → CLP/L, unidad → CLP/un; los productos a granel por kg usan `unit_weight_g`).
4. Si el conector falla, se agota el tiempo o la unidad no es convertible, se devuelve el último precio conocido con `confidence_efectiva=low` y un `warning`. **Nunca** se lanza un error al usuario. Los precios manuales no se degradan.

Sin match no hay consulta: el sistema no adivina qué producto de la cadena corresponde. La semilla trae 20 matches curados de Jumbo (spike T8). El resto se agrega desde la búsqueda en la cadena (Task 9b).

## Límites conocidos

- Se lanza un subproceso por consulta (~1 s extra). Basta con el TTL de 12 h; si el refresco masivo lo vuelve lento, se pasará a un cliente persistente.
- El endpoint llama al conector de forma síncrona; las tools MCP que lo necesiten (T16+) deberán usar la versión async.
- Los precios son del catálogo nacional (sin `branchId`), así que pueden diferir de tu sucursal.
- El conector depende de APIs internas de las cadenas. Si una cambia, el fallo se ve como `warning` y el precio cae a caché o manual.
