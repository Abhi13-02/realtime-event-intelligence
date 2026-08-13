"""
Step 5: Evolution — decide what state each cluster is in, and what that
transition is worth alerting about.

Two responsibilities, deliberately kept apart:

  classify_status()  a pure function of (previous volume, current volume).
                     No DB, no I/O, no thresholds beyond the two passed in.
                     This is the only place a status is decided.

  derive_events()    a pure function of (previous status, new status). Events
                     describe a TRANSITION, not a measurement.

Why they were split: the old implementation ran independent threshold checks,
appended each hit to an events list, and then reverse-engineered the status
back out of that list. Two consequences fell out of that design —

  1. A cluster could satisfy the growth check AND the disappearing check in the
     same run (it grew 60% but was still only 15% of its all-time peak), so it
     published two contradictory events to every subscribed user.
  2. The growth check was unconditional, so a story that kept growing re-fired
     sub_theme_growing on every single run rather than once, when it started.

Deriving events from the state transition makes both impossible by construction.

The old 'disappearing' rule also compared current volume against the all-time
peak, which is a different yardstick from the run-over-run delta used for
growth and decline. A live cluster holding 15 articles that once peaked at 100
was ruled inactive and vanished from the dashboard. Status now depends on the
run-over-run delta only; peak decay is a reporting concern, not a state.
"""
import logging
from typing import Any

from .models import _SubThemeData

logger = logging.getLogger(__name__)

# ── Status vocabulary ────────────────────────────────────────────────────────
# Mirrors the CHECK constraint added in migration 013_narrative_state.
STATUS_NEW = "new"
STATUS_GROWING = "growing"
STATUS_STEADY = "steady"
STATUS_DECLINING = "declining"
STATUS_DORMANT = "dormant"
STATUS_REVIVAL = "revival"
STATUS_REJECTED = "rejected"

# Statuses that mean "not currently visible on the live dashboard".
HIDDEN_STATUSES = (STATUS_DORMANT, STATUS_REJECTED)

# ── Event vocabulary ─────────────────────────────────────────────────────────
# Constrained by intelligence_alerts.alert_type; unchanged by this refactor.
EVENT_EMERGING = "sub_theme_emerging"
EVENT_GROWING = "sub_theme_growing"
EVENT_DISAPPEARING = "sub_theme_disappearing"
EVENT_SENTIMENT_SHIFT = "sub_theme_sentiment_shift"


def classify_status(
    prev_volume: int | None,
    volume: int,
    grow_threshold: float,
    decline_threshold: float,
) -> tuple[str, float | None]:
    """
    Decide a cluster's state from how its volume moved since the previous run.

    Returns (status, growth_pct). growth_pct is None whenever no meaningful
    baseline exists — there is no honest percentage for "appeared from nothing",
    and inventing one is what produced the old "+700%" on revived clusters,
    where a raw article count was passed through a percentage formatter.

    Args:
        prev_volume: total_volume of the previous snapshot, or None if this is
                     the first snapshot this sub-theme has ever had.
        volume:      this run's volume (news members + reddit posts, post-prune).
        grow_threshold:    positive fraction, e.g. 0.20 for +20%.
        decline_threshold: positive fraction, e.g. 0.20 for -20%.
    """
    # Emptiness wins over novelty. A cluster can be brand new and still hold
    # nothing — HDBSCAN groups it, then the similarity guard prunes every
    # member. Classifying that as 'new' would put an empty card on the live
    # dashboard, so it goes straight to dormant and stays hidden.
    if volume == 0:
        # -100% only makes sense against a real baseline. With no previous run,
        # or a previous run that was itself empty, there is no percentage to give.
        if prev_volume is None or prev_volume == 0:
            return STATUS_DORMANT, None
        return STATUS_DORMANT, -1.0

    if prev_volume is None:
        return STATUS_NEW, None

    if prev_volume == 0:
        # Came back from nothing. A percentage against zero is undefined, so the
        # state carries the meaning instead of a fabricated number.
        return STATUS_REVIVAL, None

    growth_pct = (volume - prev_volume) / prev_volume

    if growth_pct >= grow_threshold:
        return STATUS_GROWING, growth_pct
    if growth_pct <= -decline_threshold:
        return STATUS_DECLINING, growth_pct
    return STATUS_STEADY, growth_pct


def derive_events(prev_status: str | None, status: str) -> list[str]:
    """
    Translate a state transition into the events worth notifying a user about.

    Fires on the edge, not on the level: a cluster that stays 'growing' across
    five runs produces one event, not five.
    """
    if status == STATUS_REJECTED:
        return []

    # First time we have ever seen this sub-theme.
    if prev_status is None:
        return [EVENT_EMERGING] if status != STATUS_DORMANT else []

    if status == prev_status:
        return []

    if status == STATUS_DORMANT:
        return [EVENT_DISAPPEARING]

    if status == STATUS_REVIVAL:
        # A story returning from silence is a re-emergence. Reusing the emerging
        # event keeps intelligence_alerts.alert_type unchanged.
        return [EVENT_EMERGING]

    if status == STATUS_GROWING:
        return [EVENT_GROWING]

    return []


def _step5_evolution(
    cur: Any,
    sub_theme_data: list[_SubThemeData],
    settings: Any,
) -> None:
    """
    Assign status, growth_pct, prev_volume and events to every cluster.

    Reads one row per cluster: the previous snapshot. Everything after that is
    pure computation, which is what makes the rules unit-testable without a
    database (see tests/test_evolution_state_machine.py).
    """
    grow_threshold = settings.subtheme_growing_threshold
    decline_threshold = settings.subtheme_declining_threshold

    for st in sub_theme_data:
        # Losers of the identity conflict were folded into their winner.
        if st.sub_theme_id == "__merged__":
            continue

        volume = st.volume
        prev_volume: int | None = None
        prev_status: str | None = None

        # A brand-new cluster has no DB row yet, so there is nothing to read.
        if not st.is_new and st.sub_theme_id is not None:
            cur.execute("""
                SELECT total_volume, status, sentiment_score
                FROM sub_theme_snapshots
                WHERE sub_theme_id = %s
                ORDER BY snapshot_at DESC
                LIMIT 1
            """, (st.sub_theme_id,))
            prev = cur.fetchone()
            if prev is not None:
                prev_volume = prev["total_volume"] or 0
                prev_status = prev["status"]

        status, growth_pct = classify_status(
            prev_volume=prev_volume,
            volume=volume,
            grow_threshold=grow_threshold,
            decline_threshold=decline_threshold,
        )

        st.status = status
        st.growth_pct = growth_pct
        st.prev_volume = prev_volume

        events = derive_events(prev_status, status)

        # Sentiment shift is orthogonal to volume state — a story can hold a flat
        # volume while the mood around it turns — so it is checked separately and
        # never influences status.
        # Skipped for brand-new clusters: they have no sub_theme_id yet, so there
        # is no history to build a baseline from.
        if (st.sentiment_score is not None
                and status != STATUS_DORMANT
                and st.sub_theme_id is not None):
            cur.execute("""
                SELECT AVG(sentiment_score) FROM sub_theme_snapshots
                WHERE sub_theme_id = %s
                  AND sentiment_score IS NOT NULL
                  AND snapshot_at >= NOW() - INTERVAL '%s days'
            """, (st.sub_theme_id, settings.subtheme_baseline_days))
            baseline_row = cur.fetchone()
            baseline = baseline_row["avg"] if baseline_row and baseline_row["avg"] is not None else None

            if (baseline is not None
                    and abs(st.sentiment_score - baseline) >= settings.subtheme_sentiment_shift_threshold):
                events.append(EVENT_SENTIMENT_SHIFT)

        st.events = events

        logger.debug(
            "  [EVOLVE] st=%s vol=%s prev=%s -> %s (%s) events=%s",
            (st.sub_theme_id or "new")[:8], volume, prev_volume, status,
            f"{growth_pct:+.1%}" if growth_pct is not None else "n/a",
            events or "-",
        )
