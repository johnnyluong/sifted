"""item keep reason

Revision ID: 228878c93883
Revises: f29068cc10b7
Create Date: 2026-10-26 23:10:10.562717

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
import sift.db


revision: str = '228878c93883'
down_revision: Union[str, Sequence[str], None] = 'f29068cc10b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('keep_goal_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('keep_note', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('keep_reason_at', sift.db.UTCDateTime(), nullable=True))
        batch_op.create_foreign_key('fk_items_keep_goal_id_goals', 'goals', ['keep_goal_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('items', schema=None) as batch_op:
        batch_op.drop_constraint('fk_items_keep_goal_id_goals', type_='foreignkey')
        batch_op.drop_column('keep_reason_at')
        batch_op.drop_column('keep_note')
        batch_op.drop_column('keep_goal_id')
