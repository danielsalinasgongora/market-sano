# SPDX-License-Identifier: GPL-3.0-or-later
"""CLI de tokens de API (Task 15, Anexo B).

    python -m app.create_token --email ana@example.cl --name home-assistant \\
        --scopes read,write_draft

Aplica migraciones pendientes, valida el rol del usuario y muestra el token
en claro **una sola vez**.
"""

import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlmodel import Session, select

from app.db import get_engine
from app.models import User
from app.services.tokens import TokenInvalido, TokenSinPermiso, crear_token
from app.settings import get_settings

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _asegurar_esquema(database_url: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crea un token de API de Market Sano.")
    parser.add_argument("--email", required=True, help="Email del usuario dueño")
    parser.add_argument("--name", default="cli", help="Nombre para identificar el token")
    parser.add_argument(
        "--scopes",
        default="read",
        help="Scopes separados por coma: read,write_draft,confirm,admin",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    _asegurar_esquema(settings.database_url)
    engine = get_engine(settings.database_url)
    try:
        with Session(engine) as session:
            usuario = session.exec(
                select(User).where(User.email == args.email.strip().lower())
            ).first()
            if usuario is None:
                print(f"No existe un usuario con email {args.email!r}.")
                return 2
            datos = crear_token(
                session,
                usuario,
                name=args.name,
                scopes=[s for s in args.scopes.split(",") if s.strip()],
            )
    except (TokenInvalido, TokenSinPermiso) as exc:
        print(f"Error: {exc}")
        return 1
    finally:
        engine.dispose()

    print(f"Token '{datos['name']}' para {args.email} (scopes: {', '.join(datos['scopes'])})")
    print(datos["token"])
    print("Guárdalo ahora: no se volverá a mostrar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
