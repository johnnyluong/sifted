"""import budget skips

Revision ID: a876ba7567d5
Revises: b7a9e6a1c947
Create Date: 2026-10-23 18:51:30.586465

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a876ba7567d5'
down_revision: Union[str, Sequence[str], None] = 'b7a9e6a1c947'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('imports', schema=None) as batch_op:
        batch_op.add_column(sa.Column('files_skipped_budget', sa.JSON(), nullable=False, server_default='[]'))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('imports', schema=None) as batch_op:
        batch_op.drop_column('files_skipped_budget')
