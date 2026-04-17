"""drop sentiment_label from sub_theme_snapshots

Revision ID: 6a8262812ad0
Revises: 20260417_007
Create Date: 2026-04-17 14:19:30.214304

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6a8262812ad0'
down_revision: Union[str, None] = '20260417_007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # sentiment_label was already dropped directly from the DB before this migration ran.
    # This is a no-op to keep Alembic's version tracking in sync.
    pass


def downgrade() -> None:
    op.add_column(
        'sub_theme_snapshots',
        sa.Column(
            'sentiment_label',
            sa.Text(),
            nullable=True,
        )
    )
    op.create_check_constraint(
        'ck_sub_theme_snapshots_sentiment_label',
        'sub_theme_snapshots',
        "sentiment_label IN ('positive', 'neutral', 'negative')",
    )
