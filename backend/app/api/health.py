# SPDX-License-Identifier: GPL-3.0-or-later
"""Healthcheck: `GET /health` → {"status": "ok", "db": "connected"}."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlmodel import Session

from app.db import get_session

router = APIRouter(tags=["salud"])


@router.get("/health")
def health(session: Annotated[Session, Depends(get_session)]) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - solo si la BD está caída
        raise HTTPException(
            status_code=503,
            detail={"status": "error", "db": "disconnected"},
        ) from exc
    return {"status": "ok", "db": "connected"}
