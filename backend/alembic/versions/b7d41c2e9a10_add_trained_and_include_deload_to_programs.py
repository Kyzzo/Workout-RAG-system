"""add trained and include_deload to programs

Revision ID: b7d41c2e9a10
Revises: 5e6dd9edf3a5
Create Date: 2026-10-14 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d41c2e9a10'
down_revision: Union[str, Sequence[str], None] = '5e6dd9edf3a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('programs', sa.Column('trained', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column('programs', sa.Column('include_deload', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('programs', 'include_deload')
    op.drop_column('programs', 'trained')
