"""settled marker

Revision ID: 5c1e9a7d2b40
Revises: 931548f27344
Create Date: 2026-10-28 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "5c1e9a7d2b40"
down_revision: Union[str, Sequence[str], None] = "931548f27344"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SETTLED = "status IN ('kept', 'archived', 'done') AND extracted_at IS NOT NULL AND (scored_at IS NOT NULL OR wishlist)"


def upgrade() -> None:
    op.execute(f"UPDATE items SET processed_at = NULL WHERE processed_at IS NOT NULL AND NOT ({SETTLED})")
    op.execute(
        "UPDATE items SET processed_at = COALESCE(decided_at, scored_at, extracted_at) "
        f"WHERE processed_at IS NULL AND {SETTLED}"
    )


def downgrade() -> None:
    pass
