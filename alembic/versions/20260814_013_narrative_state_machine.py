"""narrative state machine — new status vocabulary and self-describing snapshots

Two changes, both in service of making a snapshot row tell the whole story
without the API having to recompute anything.

1. STATUS VOCABULARY
   The old set was ('emerging', 'active', 'declining', 'inactive'). It had no
   'growing' state, so a cluster that doubled in volume and one that sat
   perfectly flat were both stored as 'active' — the UI could not tell them
   apart, and "Active" next to a falling percentage looked like a bug.

   The new set separates the states that actually differ:

     new        first snapshot ever for this sub-theme
     growing    volume rose past the growth threshold
     steady     volume moved inside the dead band
     declining  volume fell past the decline threshold
     dormant    volume is zero this run (was 'inactive')
     revival    volume returned after a dormant run
     rejected   reserved: cluster judged off-topic and never surfaced

   'rejected' is added now, unused, so the LLM relevance gate does not have to
   migrate this constraint a second time.

2. SELF-DESCRIBING SNAPSHOTS
   prev_volume and growth_pct are written by the discovery job from the same
   numbers it classified status from, so the read path becomes a projection
   and can no longer disagree with the job.

   representative_article_id and keywords were only ever stored on sub_themes,
   which meant time-travelling to an old run showed today's headline and
   today's keywords against a historical volume. Snapshotting them makes a
   past run render as it actually was.

Revision ID: 013_narrative_state
Revises: 012_dropped_articles
Create Date: 2026-08-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "013_narrative_state"
down_revision: Union[str, None] = "012_dropped_articles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_STATUSES = "('new', 'growing', 'steady', 'declining', 'dormant', 'revival', 'rejected')"
OLD_STATUSES = "('emerging', 'active', 'declining', 'inactive')"

# Old value -> new value. 'active' cannot be split into growing/steady after the
# fact — the deltas that produced it were never stored — so it collapses to
# 'steady' and corrects itself on the next discovery run.
FORWARD_MAP = {
    "emerging": "new",
    "active": "steady",
    "declining": "declining",
    "inactive": "dormant",
}

BACKWARD_MAP = {
    "new": "emerging",
    "growing": "active",
    "steady": "active",
    "declining": "declining",
    "dormant": "inactive",
    "revival": "active",
    "rejected": "inactive",
}


def _remap(table: str, mapping: dict[str, str]) -> None:
    """Rewrite status values in place. Runs while no CHECK constraint is armed."""
    for old, new in mapping.items():
        if old == new:
            continue
        op.execute(
            sa.text(f"UPDATE {table} SET status = :new WHERE status = :old").bindparams(
                new=new, old=old
            )
        )


def upgrade() -> None:
    # ── 1. Status vocabulary ──────────────────────────────────────────────
    # Drop both constraints before touching data: a snapshot row and its
    # sub_themes row are remapped independently and must not trip each other.
    op.drop_constraint("ck_sub_themes_status", "sub_themes", type_="check")
    op.drop_constraint("ck_sts_status", "sub_theme_snapshots", type_="check")

    _remap("sub_themes", FORWARD_MAP)
    _remap("sub_theme_snapshots", FORWARD_MAP)

    op.alter_column(
        "sub_themes",
        "status",
        existing_type=sa.Text(),
        existing_nullable=False,
        server_default=sa.text("'new'"),
    )

    op.create_check_constraint("ck_sub_themes_status", "sub_themes", f"status IN {NEW_STATUSES}")
    op.create_check_constraint("ck_sts_status", "sub_theme_snapshots", f"status IN {NEW_STATUSES}")

    # ── 2. Self-describing snapshots ──────────────────────────────────────
    # All nullable: rows written before this migration have no baseline to
    # backfill from, and NULL prev_volume is exactly how the classifier spells
    # "no previous run", so old rows read correctly as 'new'.
    op.add_column("sub_theme_snapshots", sa.Column("prev_volume", sa.Integer(), nullable=True))
    op.add_column("sub_theme_snapshots", sa.Column("growth_pct", sa.Float(), nullable=True))
    op.add_column(
        "sub_theme_snapshots",
        sa.Column("representative_article_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "sub_theme_snapshots",
        sa.Column("keywords", postgresql.ARRAY(sa.Text()), nullable=True),
    )
    op.create_foreign_key(
        "fk_sts_representative_article",
        "sub_theme_snapshots",
        "articles",
        ["representative_article_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_sts_representative_article", "sub_theme_snapshots", type_="foreignkey")
    op.drop_column("sub_theme_snapshots", "keywords")
    op.drop_column("sub_theme_snapshots", "representative_article_id")
    op.drop_column("sub_theme_snapshots", "growth_pct")
    op.drop_column("sub_theme_snapshots", "prev_volume")

    op.drop_constraint("ck_sub_themes_status", "sub_themes", type_="check")
    op.drop_constraint("ck_sts_status", "sub_theme_snapshots", type_="check")

    _remap("sub_themes", BACKWARD_MAP)
    _remap("sub_theme_snapshots", BACKWARD_MAP)

    op.alter_column(
        "sub_themes",
        "status",
        existing_type=sa.Text(),
        existing_nullable=False,
        server_default=sa.text("'emerging'"),
    )

    op.create_check_constraint("ck_sub_themes_status", "sub_themes", f"status IN {OLD_STATUSES}")
    op.create_check_constraint("ck_sts_status", "sub_theme_snapshots", f"status IN {OLD_STATUSES}")
