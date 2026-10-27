"""item slides

Revision ID: 3d04f7f696c6
Revises: 4ad37bca80c7
Create Date: 2026-10-24 12:33:35.335339

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3d04f7f696c6'
down_revision: Union[str, Sequence[str], None] = '4ad37bca80c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('slide_paths', sa.JSON(none_as_null=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('items', schema=None) as batch_op:
        batch_op.drop_column('slide_paths')
