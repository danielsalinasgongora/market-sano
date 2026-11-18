# SPDX-License-Identifier: GPL-3.0-or-later
# Market Sano — imagen del backend (FastAPI + Alembic).
# Multi-arch: la base python:3.12-slim existe para linux/amd64 y linux/arm64.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# El contexto de build es la raíz del repo (ver docker-compose.yml).
COPY backend/ ./
COPY docker/entrypoint.sh /entrypoint.sh

# Instala el paquete `marketsano` y sus dependencias (fastmcp<3, etc.).
RUN pip install --no-cache-dir . && chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
