# SPDX-License-Identifier: GPL-3.0-or-later
"""Consentimiento de privacidad en usuarios (Task 13, Ley 21.719).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-19

Agrega a `users` la evidencia del consentimiento afirmativo del aviso de
privacidad: `privacy_consent_at` (UTC) y la versión del aviso aceptada.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("privacy_consent_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "privacy_consent_version",
                sqlmodel.sql.sqltypes.AutoString(length=32),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("privacy_consent_version")
        batch_op.drop_column("privacy_consent_at")
