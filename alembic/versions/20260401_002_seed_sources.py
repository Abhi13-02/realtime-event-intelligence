"""seed hacker news source

Revision ID: 002
Revises: 001
Create Date: 2026-04-01

Each team member seeds their own source in their own migration.
This file owns the Hacker News row only.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO sources (id, name, url, type, credibility_score, poll_interval, is_active)
        VALUES (
            'a1b2c3d4-0005-0005-0005-000000000005',
            'Hacker News',
            'https://news.ycombinator.com',
            'api',
            0.8,
            600,
            TRUE
        )
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM sources WHERE id = 'a1b2c3d4-0005-0005-0005-000000000005'"
    )
