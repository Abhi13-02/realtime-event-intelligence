"""add label and description to sub_theme_snapshots

Revision ID: 008_snapshot_history
Revises: 007_img_sources
Create Date: 2026-04-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "008_snapshot_history"
down_revision: Union[str, None] = "007_img_sources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sub_theme_snapshots",
        sa.Column("label", sa.Text(), nullable=True),
    )
    op.add_column(
        "sub_theme_snapshots",
        sa.Column("description", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sub_theme_snapshots", "description")
    op.drop_column("sub_theme_snapshots", "label")
