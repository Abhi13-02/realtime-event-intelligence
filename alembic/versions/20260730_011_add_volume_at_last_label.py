"""add volume_at_last_label to sub_themes for relabel decisions

Revision ID: 011_volume_at_last_label
Revises: 010_password_hash
Create Date: 2026-07-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '011_volume_at_last_label'
down_revision: Union[str, None] = '010_password_hash'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Volume (news + reddit) at the moment the label was last generated.
    # Step 4 compares current volume against this — not the latest snapshot —
    # so labels only churn on sustained growth, not per-run fluctuation.
    # Server default 0 so the relabel maths stays arithmetic, never NULL.
    op.add_column(
        'sub_themes',
        sa.Column(
            'volume_at_last_label',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ),
    )


def downgrade() -> None:
    op.drop_column('sub_themes', 'volume_at_last_label')
