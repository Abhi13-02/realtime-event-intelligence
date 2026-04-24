import logging
from typing import Any
from .models import _SubThemeData

logger = logging.getLogger(__name__)

def _step5_evolution(
    cur: Any,
    sub_theme_data: list[_SubThemeData],
    settings: Any,
) -> None:
    """
    Step 5: Evolution detection — emerging / growing / disappearing / sentiment shift.
    """
    for st in sub_theme_data:
        current_volume = len(st.members) + st.reddit_post_count
        events: list[str] = []

        if st.is_new or st.sub_theme_id is None:
            events.append("sub_theme_emerging")
            st.status = "emerging"
            st.events = events
            continue

        cur.execute("""
            SELECT total_volume, sentiment_score
            FROM sub_theme_snapshots
            WHERE sub_theme_id = %s
            ORDER BY snapshot_at DESC LIMIT 1
        """, (st.sub_theme_id,))
        prev = cur.fetchone()

        if prev is None:
            events.append("sub_theme_emerging")
            st.status = "emerging"
            st.events = events
            continue

        prev_volume = prev["total_volume"] or 0
        volume_delta = (current_volume - prev_volume) / max(prev_volume, 1)

        if volume_delta >= settings.subtheme_growing_threshold:
            events.append("sub_theme_growing")

        cur.execute(
            "SELECT MAX(total_volume) FROM sub_theme_snapshots WHERE sub_theme_id = %s",
            (st.sub_theme_id,),
        )
        peak_row = cur.fetchone()
        peak_volume = (peak_row["max"] if peak_row and peak_row["max"] else 0) or current_volume

        if peak_volume > 0 and current_volume / max(peak_volume, 1) <= settings.subtheme_disappearing_threshold:
            events.append("sub_theme_disappearing")

        if st.sentiment_score is not None:
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
                events.append("sub_theme_sentiment_shift")

        if "sub_theme_disappearing" in events:
            st.status = "inactive"
        elif "sub_theme_growing" in events:
            st.status = "active"
        elif volume_delta < 0:
            st.status = "declining"
        else:
            st.status = "active"

        st.events = events
