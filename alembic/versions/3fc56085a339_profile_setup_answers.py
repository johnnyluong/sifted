"""profile setup answers

Revision ID: 3fc56085a339
Revises: 3d04f7f696c6
Create Date: 2026-10-25 01:42:16.063861

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sift.db


revision: str = '3fc56085a339'
down_revision: Union[str, Sequence[str], None] = '3d04f7f696c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('profile', schema=None) as batch_op:
        batch_op.add_column(sa.Column('setup_answers', sa.JSON(none_as_null=True), nullable=True))
        batch_op.add_column(sa.Column('setup_at', sift.db.UTCDateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('profile', schema=None) as batch_op:
        batch_op.drop_column('setup_at')
        batch_op.drop_column('setup_answers')
