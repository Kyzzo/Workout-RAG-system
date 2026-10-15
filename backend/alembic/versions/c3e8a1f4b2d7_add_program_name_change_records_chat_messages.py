"""add program name, change records and chat messages

Revision ID: c3e8a1f4b2d7
Revises: b7d41c2e9a10
Create Date: 2026-10-14 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c3e8a1f4b2d7'
down_revision: Union[str, Sequence[str], None] = 'b7d41c2e9a10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('programs', sa.Column('name', sa.String(), nullable=True))
    op.create_table(
        'change_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('mesocycle_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('pending', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('fingerprint', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['mesocycle_id'], ['mesocycles.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_change_records_mesocycle_id', 'change_records', ['mesocycle_id'])
    op.create_table(
        'chat_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_chat_messages_user_id', 'chat_messages', ['user_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_chat_messages_user_id', table_name='chat_messages')
    op.drop_table('chat_messages')
    op.drop_index('ix_change_records_mesocycle_id', table_name='change_records')
    op.drop_table('change_records')
    op.drop_column('programs', 'name')
