# SPDX-License-Identifier: GPL-3.0-or-later
"""Autenticación local multi-usuario (spec §3.1, Task 13).

- Contraseñas con **Argon2id** (`argon2-cffi`); nunca se guardan ni devuelven en claro.
- Registro con **consentimiento afirmativo** del aviso de privacidad (Ley 21.719):
  se guarda la fecha y la versión aceptada.
- Login emite un Bearer aleatorio; en `api_tokens` solo queda su SHA-256.
- `AUTH_MODE=none` no pasa por aquí: `owner_implicito` sigue siendo el dueño del
  hogar por defecto (ver `app.services.identidad`).

Los permisos por rol y scopes se aplican en T14/T15; este módulo autentica.
"""

import hashlib
import re
import secrets
from datetime import UTC, datetime
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlmodel import Session, select

from app.models import ApiToken, Household, HouseholdMember, User
from app.models.enums import Role

PRIVACY_NOTICE_VERSION = "2026-11-19"
PRIVACY_NOTICE_SUMMARY = (
    "Market Sano guarda tus datos solo en esta instalación: email, nombre, "
    "preferencias del hogar, recetas, planes y precios consultados. No hay "
    "telemetría ni se comparten con terceros. Puedes exportar o eliminar tu "
    "hogar cuando quieras (derecho de supresión). El responsable del "
    "tratamiento es quien opera esta instancia."
)

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PASSWORD_MIN = 8
_PASSWORD_MAX = 128
_TOKEN_MAX = 512
_SCOPES_LOGIN = ["read", "write_draft"]

_hasher = PasswordHasher()  # Argon2id por defecto


class AuthError(Exception):
    """Base de errores de autenticación con mensaje accionable."""


class RegistroInvalido(AuthError):
    """Datos de registro inválidos (email, contraseña o consentimiento)."""


class EmailDuplicado(AuthError):
    """Ya existe una cuenta con ese email."""


class CredencialesInvalidas(AuthError):
    """Email o contraseña incorrectos (mismo mensaje para no filtrar cuentas)."""


class NoAutenticado(AuthError):
    """Falta el Bearer o no es válido."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def hash_token(token: str) -> str:
    """SHA-256 del Bearer: suficiente para un secreto de alta entropía."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def aviso_privacidad() -> dict[str, Any]:
    return {
        "version": PRIVACY_NOTICE_VERSION,
        "summary": PRIVACY_NOTICE_SUMMARY,
        "requires_consent": True,
        "consent_must_be_affirmative": True,
    }


def _normalizar_email(email: str) -> str:
    limpio = (email or "").strip().lower()
    if len(limpio) > 320 or not _EMAIL.match(limpio):
        raise RegistroInvalido(
            f"Email inválido: {email!r}. Usa un formato como nombre@dominio.cl."
        )
    return limpio


def _validar_password(password: str) -> None:
    if len(password) < _PASSWORD_MIN:
        raise RegistroInvalido(
            f"La contraseña debe tener al menos {_PASSWORD_MIN} caracteres."
        )
    if len(password) > _PASSWORD_MAX:
        raise RegistroInvalido(
            f"La contraseña no puede superar {_PASSWORD_MAX} caracteres."
        )


def datos_usuario(session: Session, usuario: User) -> dict[str, Any]:
    """Vista pública del usuario con su hogar y rol (sin datos sensibles)."""
    membresia = session.exec(
        select(HouseholdMember)
        .where(HouseholdMember.user_id == usuario.id)
        .order_by(HouseholdMember.joined_at)
    ).first()
    hogar = session.get(Household, membresia.household_id) if membresia else None
    return {
        "user_id": str(usuario.id),
        "email": usuario.email,
        "display_name": usuario.display_name,
        "household_id": hogar.id if hogar else None,
        "household_name": hogar.name if hogar else None,
        "role": membresia.role.value if membresia else None,
        "privacy_consent_at": (
            usuario.privacy_consent_at.isoformat() if usuario.privacy_consent_at else None
        ),
        "privacy_consent_version": usuario.privacy_consent_version,
    }


def registrar(
    session: Session,
    *,
    email: str,
    password: str,
    display_name: str,
    privacy_consent: bool,
    privacy_notice_version: str | None = None,
    household_name: str | None = None,
) -> User:
    """Crea usuario + hogar propio (owner). Exige consentimiento afirmativo."""
    if not privacy_consent:
        raise RegistroInvalido(
            "Debes aceptar el aviso de privacidad para crear la cuenta "
            f"(versión {PRIVACY_NOTICE_VERSION})."
        )
    if privacy_notice_version and privacy_notice_version != PRIVACY_NOTICE_VERSION:
        raise RegistroInvalido(
            "El aviso de privacidad cambió. Revisa la versión actual "
            f"({PRIVACY_NOTICE_VERSION}) y vuelve a aceptarlo."
        )
    email_limpio = _normalizar_email(email)
    _validar_password(password)
    nombre = (display_name or "").strip()
    if not nombre:
        raise RegistroInvalido("Indica un nombre para mostrar.")
    if session.exec(select(User).where(User.email == email_limpio)).first():
        raise EmailDuplicado(f"Ya existe una cuenta con el email {email_limpio}.")

    usuario = User(
        email=email_limpio,
        display_name=nombre[:120],
        password_hash=hash_password(password),
        privacy_consent_at=datetime.now(UTC),
        privacy_consent_version=PRIVACY_NOTICE_VERSION,
    )
    session.add(usuario)
    session.flush()

    hogar = Household(name=(household_name or f"Hogar de {nombre}").strip()[:120])
    session.add(hogar)
    session.flush()
    session.add(HouseholdMember(household_id=hogar.id, user_id=usuario.id, role=Role.owner))
    session.commit()
    session.refresh(usuario)
    return usuario


def emitir_token(session: Session, usuario: User, *, name: str = "login") -> str:
    """Crea un Bearer y guarda solo su hash. El token se muestra una vez."""
    token = secrets.token_urlsafe(32)
    session.add(
        ApiToken(
            user_id=usuario.id,
            name=name[:120],
            token_hash=hash_token(token),
            scopes=list(_SCOPES_LOGIN),
        )
    )
    session.commit()
    return token


def iniciar_sesion(session: Session, email: str, password: str) -> tuple[User, str]:
    email_limpio = (email or "").strip().lower()
    usuario = session.exec(select(User).where(User.email == email_limpio)).first()
    if usuario is None or not verify_password(usuario.password_hash, password):
        raise CredencialesInvalidas("Email o contraseña incorrectos.")
    return usuario, emitir_token(session, usuario)


def autenticar(session: Session, authorization: str | None) -> User:
    """Resuelve el usuario de un header `Authorization: Bearer <token>`."""
    if not authorization or not authorization.strip():
        raise NoAutenticado(
            "Falta el token Bearer. Envía `Authorization: Bearer <token>` o inicia "
            "sesión con `POST /api/v1/auth/login`."
        )
    partes = authorization.split(None, 1)
    if len(partes) != 2 or partes[0].lower() != "bearer" or not partes[1].strip():
        raise NoAutenticado(
            "Header Authorization inválido: se espera `Bearer <token>`."
        )
    token = partes[1].strip()
    if len(token) > _TOKEN_MAX:
        raise NoAutenticado("Token inválido o expirado.")
    fila = session.exec(
        select(ApiToken).where(ApiToken.token_hash == hash_token(token))
    ).first()
    if fila is None or fila.user_id is None:
        raise NoAutenticado("Token inválido o expirado.")
    usuario = session.get(User, fila.user_id)
    if usuario is None:
        raise NoAutenticado("Token inválido o expirado.")
    fila.last_used_at = datetime.now(UTC)
    session.add(fila)
    session.commit()
    return usuario
