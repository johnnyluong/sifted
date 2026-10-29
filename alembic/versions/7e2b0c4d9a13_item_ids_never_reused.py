"""item ids never reused

Revision ID: 7e2b0c4d9a13
Revises: 5c1e9a7d2b40
Create Date: 2026-10-28 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "7e2b0c4d9a13"
down_revision: Union[str, Sequence[str], None] = "5c1e9a7d2b40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Without AUTOINCREMENT SQLite hands a deleted newest id to the next post, which then shows the
    # deleted post's cached thumbnail and its citations in topic briefs.
    with op.batch_alter_table("items", recreate="always", table_kwargs={"sqlite_autoincrement": True}):
        pass


def downgrade() -> None:
    with op.batch_alter_table("items", recreate="always", table_kwargs={"sqlite_autoincrement": False}):
        pass
