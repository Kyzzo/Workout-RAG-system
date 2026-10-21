"""name unnamed programs by split and days, and blocks by goal

Revision ID: d4f2a9c7e1b3
Revises: c3e8a1f4b2d7
Create Date: 2026-10-21

"""
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'd4f2a9c7e1b3'
down_revision: Union[str, Sequence[str], None] = 'c3e8a1f4b2d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Generated blocks are named "Upper/Lower, 4 days/week".
_BLOCK_NAME = re.compile(r"^(?P<split>.+), (?P<days>\d+) days/week$")


def upgrade() -> None:
    # Programs left unnamed showed as "Program #33". Give each the name new
    # programs now get, e.g. "Upper/Lower · 4 days", from its first block,
    # numbering repeats per user in creation order. Renamed programs and
    # programs without a generated block are left alone.
    bind = op.get_bind()
    taken: dict[int, set[str]] = {}
    for user_id, name in bind.execute(sa.text("SELECT user_id, name FROM programs WHERE name IS NOT NULL")):
        taken.setdefault(user_id, set()).add(name)

    rows = bind.execute(sa.text(
        "SELECT p.id, p.user_id, ("
        "  SELECT m.name FROM mesocycles m WHERE m.program_id = p.id ORDER BY m.start_week, m.id LIMIT 1"
        ") AS block_name FROM programs p WHERE p.name IS NULL ORDER BY p.id"
    )).all()
    for program_id, user_id, block_name in rows:
        match = _BLOCK_NAME.match(block_name or "")
        if not match:
            continue
        base = f"{match['split']} · {match['days']} days"
        names = taken.setdefault(user_id, set())
        name, number = base, 2
        while name in names:
            name, number = f"{base} {number}", number + 1
        names.add(name)
        bind.execute(sa.text("UPDATE programs SET name = :name WHERE id = :id"), {"name": name, "id": program_id})

    # Then generated blocks, whose name now repeated the program's, become
    # "Hypertrophy block" / "Strength block" like new ones. Blocks the user
    # renamed don't match the generated pattern and are left alone.
    blocks = bind.execute(sa.text(
        "SELECT m.id, m.name, p.goal FROM mesocycles m JOIN programs p ON p.id = m.program_id"
    )).all()
    for block_id, block_name, goal in blocks:
        if _BLOCK_NAME.match(block_name or ""):
            bind.execute(
                sa.text("UPDATE mesocycles SET name = :name WHERE id = :id"),
                {"name": f"{goal.capitalize()} block", "id": block_id},
            )


def downgrade() -> None:
    # Not reversible: a filled-in default can't be told apart from a
    # program the user renamed to the same text.
    pass
