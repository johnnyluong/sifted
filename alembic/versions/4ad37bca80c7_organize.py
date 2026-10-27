"""organize

Revision ID: 4ad37bca80c7
Revises: a876ba7567d5
Create Date: 2026-10-24 01:24:22.375191

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
import sift.db


revision: str = '4ad37bca80c7'
down_revision: Union[str, Sequence[str], None] = 'a876ba7567d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('topics',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('slug', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('description', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('created_at', sift.db.UTCDateTime(), nullable=False),
    sa.Column('updated_at', sift.db.UTCDateTime(), nullable=False),
    sa.Column('merged_into_id', sa.Integer(), nullable=True),
    sa.Column('dissolved_at', sift.db.UTCDateTime(), nullable=True),
    sa.Column('brief', sa.JSON(none_as_null=True), nullable=True),
    sa.Column('brief_at', sift.db.UTCDateTime(), nullable=True),
    sa.Column('brief_model', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('brief_basis', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('pending_basis', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('pending_since', sift.db.UTCDateTime(), nullable=True),
    sa.Column('dirty_since', sift.db.UTCDateTime(), nullable=True),
    sa.Column('brief_requested_at', sift.db.UTCDateTime(), nullable=True),
    sa.CheckConstraint('brief IS NULL OR (brief_at IS NOT NULL AND brief_basis IS NOT NULL AND brief_model IS NOT NULL)', name='ck_brief_whole'),
    sa.CheckConstraint('merged_into_id IS NULL OR dissolved_at IS NULL', name='ck_one_tombstone'),
    sa.ForeignKeyConstraint(['merged_into_id'], ['topics.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug', name='uq_topics_slug')
    )
    op.create_table('topic_merge_suggestions',
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('into_id', sa.Integer(), nullable=False),
    sa.Column('suggested_at', sift.db.UTCDateTime(), nullable=False),
    sa.Column('dismissed_at', sift.db.UTCDateTime(), nullable=True),
    sa.ForeignKeyConstraint(['into_id'], ['topics.id'], ),
    sa.ForeignKeyConstraint(['source_id'], ['topics.id'], ),
    sa.PrimaryKeyConstraint('source_id', 'into_id')
    )
    op.create_table('outlines',
    sa.Column('item_id', sa.Integer(), nullable=False),
    sa.Column('extracted_at', sift.db.UTCDateTime(), nullable=False),
    sa.Column('outlined_at', sift.db.UTCDateTime(), nullable=False),
    sa.Column('model', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('gist', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('key_points', sa.JSON(none_as_null=True), nullable=False),
    sa.Column('labels', sa.JSON(none_as_null=True), nullable=False),
    sa.Column('topic_id', sa.Integer(), nullable=True),
    sa.Column('needs_topic', sa.Boolean(), nullable=False),
    sa.Column('topic_override_id', sa.Integer(), nullable=True),
    sa.Column('moved_at', sift.db.UTCDateTime(), nullable=True),
    sa.ForeignKeyConstraint(['item_id'], ['items.id'], ),
    sa.ForeignKeyConstraint(['topic_id'], ['topics.id'], ),
    sa.ForeignKeyConstraint(['topic_override_id'], ['topics.id'], ),
    sa.PrimaryKeyConstraint('item_id')
    )
    with op.batch_alter_table('outlines', schema=None) as batch_op:
        batch_op.create_index('ix_outlines_override', ['topic_override_id'], unique=False)
        batch_op.create_index('ix_outlines_topic', ['topic_id'], unique=False)

    op.create_table('outline_labels',
    sa.Column('item_id', sa.Integer(), nullable=False),
    sa.Column('label', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.ForeignKeyConstraint(['item_id'], ['outlines.item_id'], ),
    sa.PrimaryKeyConstraint('item_id', 'label')
    )
    with op.batch_alter_table('outline_labels', schema=None) as batch_op:
        batch_op.create_index('ix_outline_labels_label', ['label'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('outline_labels', schema=None) as batch_op:
        batch_op.drop_index('ix_outline_labels_label')

    op.drop_table('outline_labels')
    with op.batch_alter_table('outlines', schema=None) as batch_op:
        batch_op.drop_index('ix_outlines_topic')
        batch_op.drop_index('ix_outlines_override')

    op.drop_table('outlines')
    op.drop_table('topic_merge_suggestions')
    op.drop_table('topics')
