"""tag prescription citations and grounding notes per field

Before this, PrescriptionCitation rows and WeeklyPrescription.grounding_note
didn't record whether they belonged to the generated `sets` or `load` value,
so generating one field wiped the other's citations and overwrote its note.

Backfill for existing rows (hand-written; autogenerate would have failed on
the NOT NULL column and silently dropped every existing note):
  - citation field: inferred from the cited paper's research category. Only
    volume-category papers can back `sets` and only intensity-category
    papers can back `load`, so the paper identifies the field. The source
    ids below are the corpus as of this migration, hardcoded deliberately -
    this migration describes the data as it existed then, not a rule the app
    keeps applying.
  - citation from any other paper: inferred from which of its prescription's
    values is actually filled in; if that's ambiguous the row is DELETED
    rather than guessed. An unattributed citation that disappears
    under-claims grounding; a misattributed one would over-claim it, the
    failure mode this project treats as worse.
  - grounding note: moved to the field its prescription's citations belong
    to, else to whichever value is filled in, else copied to BOTH fields -
    when in doubt, keep the caveat visible rather than drop it.

Revision ID: 805f590eea35
Revises: 94344a66820e
Create Date: 2026-10-02 13:17:27.111655

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '805f590eea35'
down_revision: Union[str, Sequence[str], None] = '94344a66820e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SETS_SOURCES = ("weekly-sets-dose-response", "pelland-etal-2025-volume")
_LOAD_SOURCES = ("schoenfeld-etal-2021",)

# Which single value of a prescription is filled in, or NULL if both/neither.
# sets=0 / load='' is the "not generated yet" placeholder.
_FILLED_FIELD = """
    CASE
        WHEN {wp}.sets > 0 AND {wp}.load = '' THEN 'sets'
        WHEN {wp}.sets = 0 AND {wp}.load <> '' THEN 'load'
    END
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('prescription_citations', sa.Column('field', sa.String(), nullable=True))

    op.execute(sa.text("""
        UPDATE prescription_citations pc SET field = 'sets'
        FROM citations c WHERE c.id = pc.citation_id AND c.title IN :sources
    """).bindparams(sa.bindparam("sources", _SETS_SOURCES, expanding=True)))
    op.execute(sa.text("""
        UPDATE prescription_citations pc SET field = 'load'
        FROM citations c WHERE c.id = pc.citation_id AND c.title IN :sources
    """).bindparams(sa.bindparam("sources", _LOAD_SOURCES, expanding=True)))
    op.execute(f"""
        UPDATE prescription_citations pc SET field = {_FILLED_FIELD.format(wp='wp')}
        FROM weekly_prescriptions wp
        WHERE wp.id = pc.prescription_id AND pc.field IS NULL
    """)
    op.execute("DELETE FROM prescription_citations WHERE field IS NULL")
    op.alter_column('prescription_citations', 'field', nullable=False)

    op.add_column('weekly_prescriptions', sa.Column('sets_grounding_note', sa.String(), nullable=True))
    op.add_column('weekly_prescriptions', sa.Column('load_grounding_note', sa.String(), nullable=True))
    op.execute(f"""
        UPDATE weekly_prescriptions wp SET
            sets_grounding_note = CASE WHEN t.target IN ('sets', 'both') THEN wp.grounding_note END,
            load_grounding_note = CASE WHEN t.target IN ('load', 'both') THEN wp.grounding_note END
        FROM (
            SELECT w.id, COALESCE(
                (SELECT min(pc.field) FROM prescription_citations pc WHERE pc.prescription_id = w.id),
                {_FILLED_FIELD.format(wp='w')},
                'both'
            ) AS target
            FROM weekly_prescriptions w
            WHERE w.grounding_note IS NOT NULL
        ) t
        WHERE wp.id = t.id
    """)
    op.drop_column('weekly_prescriptions', 'grounding_note')


def downgrade() -> None:
    """Downgrade schema."""
    # Lossy by nature: two per-field notes collapse into one column, and
    # citations stop recording which value they back.
    op.add_column('weekly_prescriptions', sa.Column('grounding_note', sa.VARCHAR(), autoincrement=False, nullable=True))
    op.execute("UPDATE weekly_prescriptions SET grounding_note = COALESCE(sets_grounding_note, load_grounding_note)")
    op.drop_column('weekly_prescriptions', 'load_grounding_note')
    op.drop_column('weekly_prescriptions', 'sets_grounding_note')
    op.drop_column('prescription_citations', 'field')
