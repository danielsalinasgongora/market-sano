# SPDX-License-Identifier: GPL-3.0-or-later
# Market Sano — imagen del backend (FastAPI + Alembic).
# Multi-arch: la base python:3.12-slim existe para linux/amd64 y linux/arm64.

# Conector de precios mcp-supermercados-cl (MIT, Node >= 20). Se instala sin
# scripts; el backend lo lanza por stdio solo si SUPERMERCADOS_ENABLED=true.
FROM node:22-slim AS conector
RUN npm install -g --ignore-scripts mcp-supermercados-cl@1.4.9

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SUPERMERCADOS_COMMAND='["node", "/opt/mcp-supermercados-cl/dist/index.js"]'

# Runtime de Node (binario oficial) + el paquete del conector.
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=conector /usr/local/bin/node /usr/local/bin/node
COPY --from=conector /usr/local/lib/node_modules/mcp-supermercados-cl /opt/mcp-supermercados-cl

WORKDIR /app

# El contexto de build es la raíz del repo (ver docker-compose.yml).
COPY backend/ ./
COPY docker/entrypoint.sh /entrypoint.sh

# Instala el paquete `marketsano` y sus dependencias (fastmcp<3, etc.).
RUN pip install --no-cache-dir . && chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
