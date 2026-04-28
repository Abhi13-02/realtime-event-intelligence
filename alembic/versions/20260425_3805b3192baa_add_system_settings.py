"""add_system_settings

Revision ID: 3805b3192baa
Revises: 009_feed_control
Create Date: 2026-04-25 04:09:19.132633

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3805b3192baa'
down_revision: Union[str, None] = '009_feed_control'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create system_settings table
    op.create_table(
        'system_settings',
        sa.Column('key', sa.Text(), nullable=False),
        sa.Column('value', sa.JSON(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('key')
    )

    # 2. Seed initial thresholds
    # We use JSON because 'value' column is JSONB
    op.execute("""
        INSERT INTO system_settings (key, value, description) VALUES
        ('threshold_broad', '0.3', 'Cosine similarity floor for BROAD sensitivity topics'),
        ('threshold_balanced', '0.35', 'Cosine similarity floor for BALANCED sensitivity topics'),
        ('threshold_high', '0.4', 'Cosine similarity floor for HIGH sensitivity topics')
    """)


def downgrade() -> None:
    op.drop_table('system_settings')
