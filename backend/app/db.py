# SPDX-License-Identifier: GPL-3.0-or-later
"""Motor de base de datos y sesión (SQLModel).

SQLite se configura con WAL y foreign keys activos. El motor vive en
`app.state.engine` (inyectado por `create_app`) para que los tests puedan
construir apps aisladas con su propia base temporal.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import Request
from sqlalchemy import Engine, event, make_url
from sqlmodel import Session, create_engine


def get_engine(database_url: str) -> Engine:
    """Crea el motor según la URL (SQLite o Postgres).

    Para SQLite en archivo, asegura que el directorio padre exista:
    evita el clásico `unable to open database file` del primer arranque.
    """
    url = make_url(database_url)
    connect_args: dict[str, Any] = {}

    if url.get_backend_name() == "sqlite":
        # FastAPI puede usar la conexión desde varios hilos.
        connect_args["check_same_thread"] = False
        db_path = url.database
        if db_path and db_path != ":memory:":
            Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)

    if url.get_backend_name() == "sqlite":

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def get_session(request: Request) -> Iterator[Session]:
    """Dependencia FastAPI: una sesión por request, del motor de la app."""
    with Session(request.app.state.engine) as session:
        yield session
