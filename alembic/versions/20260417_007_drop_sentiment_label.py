"""Drop sentiment_label column from sub_theme_snapshots.

Revision ID: 20260417_007
Revises: 20260417_baadeb99e8ac
Create Date: 2026-04-17
"""
from alembic import op

revision = "20260417_007"
down_revision = "baadeb99e8ac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("sub_theme_snapshots", "sentiment_label")


def downgrade() -> None:
    op.add_column(
        "sub_theme_snapshots",
        op.Column(
            "sentiment_label",
            op.String(),
            nullable=True,
        ),
    )
