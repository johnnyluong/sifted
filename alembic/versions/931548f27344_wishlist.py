"""wishlist

Revision ID: 931548f27344
Revises: 228878c93883
Create Date: 2026-10-27 18:08:52.516122

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '931548f27344'
down_revision: Union[str, Sequence[str], None] = '228878c93883'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('wishlist', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('wishlist_override', sa.Boolean(), nullable=True))
        batch_op.create_check_constraint(
            'ck_wishlist_override', 'wishlist_override IS NULL OR wishlist = wishlist_override'
        )
    # ProductDetails.wishlist is required, so stored product cards need it to parse.
    op.execute(
        "UPDATE items SET details = json_set(details, '$.wishlist', json('false')) "
        "WHERE item_type = 'product' AND details IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DELETE FROM digest_entries WHERE role = 'wishlist'")
    op.execute(
        "UPDATE items SET details = json_remove(details, '$.wishlist') "
        "WHERE item_type = 'product' AND details IS NOT NULL"
    )
    with op.batch_alter_table('items', schema=None) as batch_op:
        batch_op.drop_constraint('ck_wishlist_override', type_='check')
        batch_op.drop_column('wishlist_override')
        batch_op.drop_column('wishlist')
