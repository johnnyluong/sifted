"""digest queue

Revision ID: f29068cc10b7
Revises: 3fc56085a339
Create Date: 2026-10-25 01:50:26.557658

"""
import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'f29068cc10b7'
down_revision: Union[str, Sequence[str], None] = '3fc56085a339'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE = sa.Enum('pick', 'new', 'carryover', name='digestrole')
PICKS_HEADING = "## Top 3 to act on this week"
PICK = re.compile(r"^\d+\. \*\*\[.*\]\(/items/(\d+)\)\*\*\n\n   (.*)\n\n   Next: (.*)$", re.M)
LINE = re.compile(r"^- \[.*\]\(/items/(\d+)\): (.*)$", re.M)


def upgrade() -> None:
    with op.batch_alter_table('digest_entries', schema=None) as batch_op:
        batch_op.add_column(sa.Column('position', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('why', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('next_action', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('line', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    with op.batch_alter_table('digests', schema=None) as batch_op:
        batch_op.add_column(sa.Column('opening', sqlmodel.sql.sqltypes.AutoString(), nullable=True))

    _queue_from_markdown()

    with op.batch_alter_table('digest_entries', schema=None) as batch_op:
        batch_op.alter_column(
            'section', new_column_name='role', existing_type=sa.VARCHAR(), type_=ROLE, existing_nullable=False
        )
        batch_op.alter_column('position', existing_type=sa.Integer(), nullable=False)
        batch_op.create_unique_constraint('uq_digest_entries_position', ['digest_id', 'position'])
    with op.batch_alter_table('digests', schema=None) as batch_op:
        batch_op.drop_column('content_md')


def downgrade() -> None:
    with op.batch_alter_table('digests', schema=None) as batch_op:
        batch_op.add_column(sa.Column('content_md', sa.VARCHAR(), nullable=False, server_default=''))

    _markdown_from_queue()
    op.execute("DELETE FROM digest_entries WHERE role = 'carryover'")
    op.execute("UPDATE digest_entries SET role = CASE role WHEN 'pick' THEN 'top' ELSE 'goal' END")

    with op.batch_alter_table('digest_entries', schema=None) as batch_op:
        batch_op.drop_constraint('uq_digest_entries_position', type_='unique')
        batch_op.alter_column(
            'role', new_column_name='section', existing_type=ROLE, type_=sa.VARCHAR(), existing_nullable=False
        )
        batch_op.drop_column('line')
        batch_op.drop_column('next_action')
        batch_op.drop_column('why')
        batch_op.drop_column('position')
    with op.batch_alter_table('digests', schema=None) as batch_op:
        batch_op.alter_column('content_md', existing_type=sa.VARCHAR(), server_default=None)
        batch_op.drop_column('opening')


def _queue_from_markdown() -> None:
    conn = op.get_bind()
    items = {r.id: r for r in conn.execute(sa.text("SELECT id, relevance_reason, next_action, summary FROM items"))}
    for digest_id, md in conn.execute(sa.text("SELECT id, content_md FROM digests")).all():
        picks = {int(m[1]): (m[2].strip(), m[3].strip()) for m in PICK.finditer(md)}
        lines = {int(m[1]): m[2].strip() for m in LINE.finditer(md)}
        entries = conn.execute(
            sa.text("SELECT item_id, section FROM digest_entries WHERE digest_id = :d ORDER BY rowid"), {"d": digest_id}
        ).all()

        def first_seen(item_id: int) -> int:
            at = md.find(f"(/items/{item_id})")
            return at if at >= 0 else len(md)

        for position, (item_id, section) in enumerate(sorted(entries, key=lambda e: first_seen(e.item_id)), 1):
            item = items.get(item_id)
            is_pick = section == 'top'
            why, action = picks.get(item_id, (None, None)) if is_pick else (None, None)
            conn.execute(
                sa.text(
                    "UPDATE digest_entries SET position = :p, section = :role, why = :why, next_action = :next, "
                    "line = :line WHERE digest_id = :d AND item_id = :i"
                ),
                {
                    "p": position,
                    "role": 'pick' if is_pick else 'new',
                    "why": why or (item.relevance_reason if item else None),
                    "next": action or (item.next_action if item else None),
                    "line": None if is_pick else lines.get(item_id) or (item.summary if item else None),
                    "d": digest_id,
                    "i": item_id,
                },
            )
        opening = md.split(PICKS_HEADING, 1)[0].strip() if PICKS_HEADING in md else ""
        conn.execute(sa.text("UPDATE digests SET opening = :o WHERE id = :d"), {"o": opening or None, "d": digest_id})


def _markdown_from_queue() -> None:
    conn = op.get_bind()
    for digest_id, opening in conn.execute(sa.text("SELECT id, opening FROM digests")).all():
        rows = conn.execute(
            sa.text(
                "SELECT e.item_id, e.role, e.why, e.next_action, e.line, coalesce(i.title, 'Untitled') AS title "
                "FROM digest_entries e LEFT JOIN items i ON i.id = e.item_id "
                "WHERE e.digest_id = :d AND e.role != 'carryover' ORDER BY e.position"
            ),
            {"d": digest_id},
        ).all()
        out = [opening, ""] if opening else []
        out.append(PICKS_HEADING)
        for n, r in enumerate((r for r in rows if r.role == 'pick'), 1):
            out += [f"{n}. **[{r.title}](/items/{r.item_id})**", "", f"   {r.why or ''}", "", f"   Next: {r.next_action or ''}", ""]
        rest = [f"- [{r.title}](/items/{r.item_id}): {r.line or ''}" for r in rows if r.role == 'new']
        if rest:
            out += ["", "## By goal", "", *rest]
        conn.execute(
            sa.text("UPDATE digests SET content_md = :md WHERE id = :d"), {"md": "\n".join(out).strip() + "\n", "d": digest_id}
        )
