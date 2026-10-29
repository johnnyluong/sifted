"""released links outlive posts

Revision ID: 6cf92d9cd6bf
Revises: 7e2b0c4d9a13
Create Date: 2026-10-28 15:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "6cf92d9cd6bf"
down_revision: Union[str, Sequence[str], None] = "7e2b0c4d9a13"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("import_links", schema=None) as batch_op:
        batch_op.drop_constraint("ck_released_has_item", type_="check")
        batch_op.create_check_constraint("ck_released_has_time", "state != 'released' OR released_at IS NOT NULL")


def downgrade() -> None:
    # The old check needs a post on every released link. Skipped keeps released_at, which the old cap still counts.
    op.execute("UPDATE import_links SET state = 'skipped' WHERE state = 'released' AND item_id IS NULL")
    with op.batch_alter_table("import_links", schema=None) as batch_op:
        batch_op.drop_constraint("ck_released_has_time", type_="check")
        batch_op.create_check_constraint(
            "ck_released_has_item", "state != 'released' OR (item_id IS NOT NULL AND released_at IS NOT NULL)"
        )
