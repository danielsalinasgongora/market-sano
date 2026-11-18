<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Conectar Claude Desktop (o Cursor) con Market Sano

El servidor MCP de Market Sano corre **en tu máquina** por stdio y habla directamente con tu base local. No hay nube: tus datos no salen de tu computador.

## 1. Preparar el backend (una sola vez)

```bash
git clone https://github.com/danielsalinasgongora/market-sano.git
cd market-sano/backend

# Python 3.12+ y entorno virtual
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"      # Windows
# pip install -e ".[dev]"                  # Linux/macOS

# Migraciones + datos de ejemplo (hogar, catálogo, 14 recetas chilenas)
.venv\Scripts\python -m app.seed
```

> **Con Docker (recomendado si quieres precios en vivo):** `docker compose up -d` y luego `docker compose exec -T app python -m app.seed`. El servidor MCP corre **dentro** del contenedor (misma base, conector incluido) y Claude Desktop le habla por `docker exec -i`:
>
> ```json
> {
>   "mcpServers": {
>     "market-sano": {
>       "command": "docker",
>       "args": ["exec", "-i", "market-sano-app-1", "python", "-m", "app.mcp_server"]
>     }
>   }
> }
> ```
>
> Requiere que el contenedor esté corriendo. Con esta opción puedes saltarte la sección 2.

## 2. Registrar el servidor en Claude Desktop

Abre la configuración de Claude Desktop:

- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

Agrega el servidor `market-sano` dentro de `mcpServers`. Ejemplo Windows (ajusta las rutas a tu instalación):

```json
{
  "mcpServers": {
    "market-sano": {
      "command": "C:\\ruta\\al\\repo\\market-sano\\backend\\.venv\\Scripts\\python.exe",
      "args": ["-m", "app.mcp_server"],
      "env": {
        "PYTHONPATH": "C:\\ruta\\al\\repo\\market-sano\\backend",
        "DATABASE_URL": "sqlite:///C:/ruta/al/repo/market-sano/backend/data/app.db"
      }
    }
  }
}
```

Notas:

- `DATABASE_URL` debe ser **absoluta** (`sqlite:///` + ruta del archivo con `/`), porque Claude Desktop no define el directorio de trabajo del proceso.
- Si instalaste el paquete en el venv (`pip install -e .`), `PYTHONPATH` es opcional; incluirlo no hace daño.
- Reinicia Claude Desktop después de guardar el JSON.

## 3. Probar

Con una base sembrada, pide en el chat:

> "Con la tool `get_household_context` de market-sano: ¿cuál es mi presupuesto semanal y en qué tienda compro por defecto?"

Deberías obtener: **45.000 CLP** y **jumbo**. Luego prueba:

> "Usa `search_recipes` con tags `["chilena", "guiso"]` y muéstrame los títulos."
> "¿Qué tengo en la despensa que venza esta semana? (`get_pantry_status`)"

## Cursor

Equivalentemente, en `.cursor/mcp.json` del proyecto:

```json
{
  "mcpServers": {
    "market-sano": {
      "command": "C:\\ruta\\al\\repo\\market-sano\\backend\\.venv\\Scripts\\python.exe",
      "args": ["-m", "app.mcp_server"],
      "env": {
        "PYTHONPATH": "C:\\ruta\\al\\repo\\market-sano\\backend",
        "DATABASE_URL": "sqlite:///C:/ruta/al/repo/market-sano/backend/data/app.db"
      }
    }
  }
}
```

## Solución de problemas

| Síntoma | Causa probable |
|---|---|
| El servidor no aparece | JSON con sintaxis inválida; revisa comas y escapes `\\` |
| "No hay hogares en la base" | Ejecuta `python -m app.seed` con el mismo `DATABASE_URL` del config |
| Tools no listadas | El venv no tiene `fastmcp` instalado: `pip install -e ".[dev]"` de nuevo |
| Base vacía tras sembrar | `DATABASE_URL` distinta entre la semilla y el config (usa rutas absolutas en ambos) |
