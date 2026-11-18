"""matches por cadena y peso por unidad

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-18

SPDX-License-Identifier: GPL-3.0-or-later

- `product_store_matches`: producto del catálogo ↔ producto concreto de una
  cadena (URL/SKU), decidido en el spike T8. Lo usa el refresco live (T9) y el
  catálogo abierto (T9b).
- `product_catalog.unit_weight_g`: peso medio de una unidad, para convertir el
  PPUM por kg de los productos a granel cuando el catálogo cuenta por unidad.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('product_store_matches',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('product_id', sa.Integer(), nullable=False),
    sa.Column('store_id', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
    sa.Column('store_url', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False),
    sa.Column('sku', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
    sa.Column('matched_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['product_id'], ['product_catalog.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('product_id', 'store_id', name='uq_product_store_matches_product_store')
    )
    with op.batch_alter_table('product_catalog') as batch_op:
        batch_op.add_column(sa.Column('unit_weight_g', sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('product_catalog') as batch_op:
        batch_op.drop_column('unit_weight_g')
    op.drop_table('product_store_matches')
