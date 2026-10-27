"""initial schema

Revision ID: 4273481df2a5
Revises: 
Create Date: 2026-10-22 21:07:51.810427

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
import sift.db


# revision identifiers, used by Alembic.
revision: str = '4273481df2a5'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('digests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('period_start', sift.db.UTCDateTime(), nullable=False),
    sa.Column('period_end', sift.db.UTCDateTime(), nullable=False),
    sa.Column('created_at', sift.db.UTCDateTime(), nullable=False),
    sa.Column('content_md', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('model', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('sent_at', sift.db.UTCDateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('goals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('description', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('category', sa.Enum('personal', 'professional', 'entrepreneurial', 'other', name='goalcategory'), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sift.db.UTCDateTime(), nullable=False),
    sa.Column('updated_at', sift.db.UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('profile',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('values_text', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('updated_at', sift.db.UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.Enum('instagram', 'threads', name='source'), nullable=False),
    sa.Column('canonical_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('url', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('clean_url', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('origin_channel', sa.Enum('web', 'cli', 'api', 'telegram', name='channel'), nullable=False),
    sa.Column('origin_reply_to', sa.JSON(), nullable=True),
    sa.Column('received_at', sift.db.UTCDateTime(), nullable=False),
    sa.Column('status', sa.Enum('queued', 'fetching', 'processing', 'kept', 'archived', 'done', 'failed', name='itemstatus'), nullable=False),
    sa.Column('status_reason', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('failure_kind', sa.Enum('download_failed', 'transcription_failed', 'llm_failed', 'unsupported_url', name='failurekind'), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('next_attempt_at', sift.db.UTCDateTime(), nullable=True),
    sa.Column('last_error', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('claim_token', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('claimed_at', sift.db.UTCDateTime(), nullable=True),
    sa.Column('fetched_at', sift.db.UTCDateTime(), nullable=True),
    sa.Column('media_kind', sa.Enum('video', 'image', 'text', name='mediakind'), nullable=True),
    sa.Column('author_handle', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('caption', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('post_text', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('raw_metadata', sa.JSON(), nullable=True),
    sa.Column('media_path', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('thumbnail_path', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('fetch_notes', sa.JSON(), nullable=True),
    sa.Column('media_processed_at', sift.db.UTCDateTime(), nullable=True),
    sa.Column('transcript', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('frame_paths', sa.JSON(), nullable=True),
    sa.Column('extracted_at', sift.db.UTCDateTime(), nullable=True),
    sa.Column('extract_model', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('item_type', sa.Enum('place', 'recipe', 'playbook', 'idea', 'product', 'other', name='itemtype'), nullable=True),
    sa.Column('title', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('summary', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('details', sa.JSON(), nullable=True),
    sa.Column('next_action', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('ocr_text', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('scored_at', sift.db.UTCDateTime(), nullable=True),
    sa.Column('score_model', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('relevance_score', sa.Integer(), nullable=True),
    sa.Column('matched_goal_id', sa.Integer(), nullable=True),
    sa.Column('relevance_reason', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('model_decision', sa.Enum('keep', 'archive', name='decision'), nullable=True),
    sa.Column('threshold_decision', sa.Enum('keep', 'archive', name='decision'), nullable=True),
    sa.Column('user_override', sa.Enum('keep', 'archive', name='decision'), nullable=True),
    sa.Column('overridden_at', sift.db.UTCDateTime(), nullable=True),
    sa.Column('last_interacted_at', sift.db.UTCDateTime(), nullable=True),
    sa.Column('decided_at', sift.db.UTCDateTime(), nullable=True),
    sa.Column('processed_at', sift.db.UTCDateTime(), nullable=True),
    sa.Column('done_at', sift.db.UTCDateTime(), nullable=True),
    sa.CheckConstraint("status != 'failed' OR failure_kind IS NOT NULL", name='ck_failed_has_kind'),
    sa.CheckConstraint("status NOT IN ('fetching','processing') OR claim_token IS NOT NULL", name='ck_running_has_claim'),
    sa.CheckConstraint('extracted_at IS NULL OR (item_type IS NOT NULL AND title IS NOT NULL AND details IS NOT NULL)', name='ck_extract_complete'),
    sa.CheckConstraint('scored_at IS NULL OR (relevance_score IS NOT NULL AND threshold_decision IS NOT NULL)', name='ck_score_complete'),
    sa.ForeignKeyConstraint(['matched_goal_id'], ['goals.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'canonical_id', name='uq_items_source_canonical')
    )
    with op.batch_alter_table('items', schema=None) as batch_op:
        batch_op.create_index('ix_items_claim', ['status', 'next_attempt_at', 'received_at'], unique=False)

    op.create_table('digest_entries',
    sa.Column('digest_id', sa.Integer(), nullable=False),
    sa.Column('item_id', sa.Integer(), nullable=False),
    sa.Column('section', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.ForeignKeyConstraint(['digest_id'], ['digests.id'], ),
    sa.ForeignKeyConstraint(['item_id'], ['items.id'], ),
    sa.PrimaryKeyConstraint('digest_id', 'item_id')
    )
    with op.batch_alter_table('digest_entries', schema=None) as batch_op:
        batch_op.create_index('ix_digest_entries_item', ['item_id'], unique=False)



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('digest_entries', schema=None) as batch_op:
        batch_op.drop_index('ix_digest_entries_item')

    op.drop_table('digest_entries')
    with op.batch_alter_table('items', schema=None) as batch_op:
        batch_op.drop_index('ix_items_claim')

    op.drop_table('items')
    op.drop_table('profile')
    op.drop_table('goals')
    op.drop_table('digests')
