"""historical memberships — make sub_theme_memberships append-only per run

sub_theme_memberships was current-state-only by design: every discovery run
deleted a sub-theme's rows and re-inserted them. Three things fell out of that.

1. Clicking a point on a narrative's timeline could never show the articles that
   were in the cluster at that moment — only the ones in it right now.

2. When a cluster was sunsetted, its members were deleted and nothing was put
   back, so the detail page for a dormant narrative would open with a correct
   header, a correct graph, and an empty evidence list.

3. Identity resolution has no way to ask "which articles were in this sub-theme
   last run?", which is the single most reliable signal for deciding whether a
   freshly clustered group is the same story as an existing one.

Adding run_at and widening the unique key turns the table into a time series
keyed the same way sub_theme_snapshots already is, so a membership row and the
snapshot describing the same run share one timestamp and join exactly.

Revision ID: 014_hist_memberships
Revises: 013_narrative_state
Create Date: 2026-08-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "014_hist_memberships"
down_revision: Union[str, None] = "013_narrative_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable first so existing rows can be backfilled before the NOT NULL.
    op.add_column(
        "sub_theme_memberships",
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=True),
    )

    # created_at is the closest thing the old rows have to a run timestamp: they
    # were written by the run that last replaced them.
    op.execute("UPDATE sub_theme_memberships SET run_at = created_at WHERE run_at IS NULL")

    op.alter_column(
        "sub_theme_memberships",
        "run_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )

    # The old key allowed one row per (sub_theme, article) for all time, which is
    # precisely what forced the delete-and-replace cycle.
    op.drop_constraint("uq_stm_sub_theme_article", "sub_theme_memberships", type_="unique")
    op.create_unique_constraint(
        "uq_stm_sub_theme_article_run",
        "sub_theme_memberships",
        ["sub_theme_id", "article_id", "run_at"],
    )

    # Serves the primary read: "members of this sub-theme as of this run",
    # and the identity-resolution lookup of the most recent run's member set.
    op.create_index(
        "idx_stm_sub_theme_run_at",
        "sub_theme_memberships",
        ["sub_theme_id", "run_at"],
    )


def downgrade() -> None:
    # Collapsing back to one row per (sub_theme, article) means discarding every
    # run but the newest — the old shape cannot represent the history.
    op.execute("""
        DELETE FROM sub_theme_memberships m
        USING (
            SELECT sub_theme_id, article_id, MAX(run_at) AS keep_at
            FROM sub_theme_memberships
            GROUP BY sub_theme_id, article_id
        ) latest
        WHERE m.sub_theme_id = latest.sub_theme_id
          AND m.article_id   = latest.article_id
          AND m.run_at      <> latest.keep_at
    """)

    op.drop_index("idx_stm_sub_theme_run_at", table_name="sub_theme_memberships")
    op.drop_constraint("uq_stm_sub_theme_article_run", "sub_theme_memberships", type_="unique")
    op.create_unique_constraint(
        "uq_stm_sub_theme_article",
        "sub_theme_memberships",
        ["sub_theme_id", "article_id"],
    )
    op.drop_column("sub_theme_memberships", "run_at")
