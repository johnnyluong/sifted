"""import skipped files

Revision ID: b7a9e6a1c947
Revises: eef775d33380
Create Date: 2026-10-23 18:22:50.369106

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7a9e6a1c947'
down_revision: Union[str, Sequence[str], None] = 'eef775d33380'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('imports', schema=None) as batch_op:
        batch_op.add_column(sa.Column('files_skipped_large', sa.JSON(), nullable=False, server_default='[]'))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('imports', schema=None) as batch_op:
        batch_op.drop_column('files_skipped_large')
