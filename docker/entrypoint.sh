#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Market Sano — entrypoint del contenedor app.
# Aplica las migraciones y luego inicia la API (spec §3.11).

set -e

echo "Market Sano: aplicando migraciones (alembic upgrade head)..."
alembic upgrade head

echo "Market Sano: iniciando API en :8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
