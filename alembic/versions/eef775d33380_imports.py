"""imports

Revision ID: eef775d33380
Revises: 4273481df2a5
Create Date: 2026-10-23 17:43:21.783271

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
import sift.db


# revision identifiers, used by Alembic.
revision: str = 'eef775d33380'
down_revision: Union[str, Sequence[str], None] = '4273481df2a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # items.origin_channel gains 'export' with no op: SQLite stores the enum as a VARCHAR without a CHECK.
    op.create_table('imports',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('filename', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('created_at', sift.db.UTCDateTime(), nullable=False),
    sa.Column('updated_at', sift.db.UTCDateTime(), nullable=False),
    sa.Column('files_read', sa.JSON(), nullable=False),
    sa.Column('unsupported', sa.JSON(), nullable=False),
    sa.Column('unsupported_count', sa.Integer(), nullable=False),
    sa.Column('max_posts', sa.Integer(), nullable=True),
    sa.Column('started_at', sift.db.UTCDateTime(), nullable=True),
    sa.Column('paused_at', sift.db.UTCDateTime(), nullable=True),
    sa.Column('pause_reason', sa.Enum('user', 'download_failures', name='pausereason'), nullable=True),
    sa.Column('resumed_at', sift.db.UTCDateTime(), nullable=True),
    sa.Column('cancelled_at', sift.db.UTCDateTime(), nullable=True),
    sa.Column('next_release_at', sift.db.UTCDateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('import_links',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('import_id', sa.Integer(), nullable=False),
    sa.Column('source', sa.Enum('instagram', 'threads', name='source'), nullable=False),
    sa.Column('canonical_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('clean_url', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('url', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('saved_at', sift.db.UTCDateTime(), nullable=True),
    sa.Column('state', sa.Enum('found', 'waiting', 'released', 'duplicate', 'skipped', name='linkstate'), nullable=False),
    sa.Column('item_id', sa.Integer(), nullable=True),
    sa.Column('released_at', sift.db.UTCDateTime(), nullable=True),
    sa.CheckConstraint("state != 'released' OR (item_id IS NOT NULL AND released_at IS NOT NULL)", name='ck_released_has_item'),
    sa.ForeignKeyConstraint(['import_id'], ['imports.id'], ),
    sa.ForeignKeyConstraint(['item_id'], ['items.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('import_id', 'source', 'canonical_id', name='uq_import_links_ref')
    )
    with op.batch_alter_table('import_links', schema=None) as batch_op:
        batch_op.create_index('ix_import_links_drip', ['state', 'import_id', 'saved_at'], unique=False)
        batch_op.create_index('ix_import_links_released', ['released_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('import_links', schema=None) as batch_op:
        batch_op.drop_index('ix_import_links_released')
        batch_op.drop_index('ix_import_links_drip')

    op.drop_table('import_links')
    op.drop_table('imports')
