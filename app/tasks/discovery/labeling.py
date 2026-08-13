import json
import logging
from typing import Any

import numpy as np
from groq import Groq
from scipy.optimize import linear_sum_assignment

from .models import _SubThemeData, _cosine_similarity, _parse_pgvector
from .clustering import _prune_low_similarity_members

logger = logging.getLogger(__name__)

def _call_groq_label(
    groq_client: Groq,
    topic_name: str,
    keywords: list[str],
    sample_headlines: list[str],
    article_count: int,
    reddit_count: int,
    sentiment_score: float | None,
    sample_comments: list[str] = None,
) -> tuple[str | None, str | None]:
    """
    Call Groq to generate a sub-theme label + description using news and social signal.
    """
    comments_section = ""
    if sample_comments:
        comments_section = "\nPEOPLE'S VOICES (Top Reddit Comments):\n" + "\n".join(f"- {c[:200]}..." for c in sample_comments[:5])

    prompt = f"""You are an expert news analyst. Your task is to identify and label an emerging story within a broader topic.
    
BROADER TOPIC: {topic_name}
CORE KEYWORDS: {", ".join(keywords)}

REPRESENTATIVE HEADLINES:
{chr(10).join(f"- {h}" for h in sample_headlines[:10])}
{comments_section}

METRICS: {article_count} news reports, {reddit_count} social discussions.
SENTIMENT: {f"{sentiment_score:+.2f}" if sentiment_score is not None else "N/A"}

TASK:
1. Generate a LABEL (3-7 words).
   - Use SIMPLE, PLAIN ENGLISH that anyone on the street would understand.
   - NO JARGON. NO corporate speak.
   - Dont keep it general , it should be specific to the story.
   - GOOD: "People worried about AI taking jobs", "Google's big gamble on AI agents"
   - BAD: "Generative AI workforce integration trends"

2. Generate a 1-3 sentence DESCRIPTION.
   - Start directly with the facts.
   - Use simple language.
   - If the "PEOPLE'S VOICES" show a clear pattern (e.g., people are angry, scared, or excited), mention what people are saying.
   - EXAMPLE: "Major tech companies are replacing entry-level staff with AI tools. On social media, workers are expressing deep fear about their career futures and calling for new labor protections."

Return ONLY a JSON object with keys "label" and "description"."""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.choices[0].message.content.strip()
            # Handle possible markdown blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
                
            result = json.loads(content)
            return result.get("label"), result.get("description")
        except Exception as exc:
            logger.warning("Groq labeling attempt %d/%d failed: %s", attempt + 1, max_retries, exc)
            if attempt == max_retries - 1:
                return None, None
    return None, None

def _jaccard(a: set, b: set) -> float:
    """Overlap between two article-id sets. 0.0 when either is empty."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def identity_score(
    jaccard: float,
    cosine: float,
    jaccard_threshold: float,
    centroid_threshold: float,
    drift_floor: float,
) -> float:
    """
    How strongly a freshly clustered group claims an existing sub-theme's identity.
    Returns 0.0 for "no claim". Higher is a stronger claim.

    Pure function — see tests/test_identity_matching.py.

    THE MEASUREMENT THIS IS BUILT ON (docs/discovery-accuracy-log.md v2):
    the old matcher compared a cluster against a centroid frozen at creation
    time. Once the rolling window turned over, the same story scored 0.790 on
    average against its own frozen centroid, while genuinely different stories
    peaked at 0.803. Those distributions OVERLAP, so no cosine threshold can
    separate "same story, fresh articles" from "different story" — at 0.85 all
    twenty benchmark stories lost their identity, were recreated as new, and had
    their originals sunsetted. That is the ghost-cluster failure.

    So identity is carried by ARTICLE OVERLAP, which does separate cleanly:
    consecutive runs share ~92% of the window, and Jaccard falls monotonically
    as it rotates. Cosine is demoted to a fallback for when there is no
    membership history to compare against, and to a veto.

    Ordering is tiered, not a weighted sum: an overlap match always outranks a
    cosine-only match, because a shared article set is direct evidence while a
    similar centroid is circumstantial.
    """
    # VETO. The stored centroid is never updated, so it is a permanent record of
    # what this narrative was when it was born. Falling this far from it means
    # the story has genuinely become something else, and it is forked no matter
    # how many articles it shares — this is what stops a chain of high-overlap
    # runs slowly walking one narrative into a different one.
    if cosine < drift_floor:
        return 0.0

    if jaccard >= jaccard_threshold:
        return 1.0 + jaccard      # overlap tier — always beats cosine-only
    if cosine >= centroid_threshold:
        return cosine             # cosine tier — no membership history to use
    return 0.0


def _load_identity_candidates(cur: Any, topic_id: str) -> list[dict]:
    """
    Every sub-theme in this topic that a new cluster could claim, together with
    the article set it held on its most recent run.

    Rejected sub-themes are excluded: they were judged off-topic and must not be
    resurrected. Dormant ones ARE included — a story returning from silence
    should reclaim its own identity rather than appear as a stranger.
    """
    cur.execute("""
        SELECT st.id,
               st.label,
               st.description,
               st.label_generated_at,
               st.volume_at_last_label,
               st.centroid::text AS centroid,
               COALESCE(m.article_ids, ARRAY[]::uuid[]) AS prev_article_ids
        FROM sub_themes st
        LEFT JOIN LATERAL (
            -- The member set as of this sub-theme's latest run. Available only
            -- because memberships became append-only with a run_at stamp.
            SELECT ARRAY_AGG(article_id) AS article_ids
            FROM sub_theme_memberships
            WHERE sub_theme_id = st.id
              AND run_at = (
                  SELECT MAX(run_at) FROM sub_theme_memberships
                  WHERE sub_theme_id = st.id
              )
        ) m ON TRUE
        WHERE st.topic_id = %s
          AND st.status != 'rejected'
    """, (topic_id,))

    candidates = []
    for row in cur.fetchall():
        candidates.append({
            "db_id": str(row["id"]),
            "db_label": row["label"],
            "db_description": row["description"],
            "db_label_generated_at": row["label_generated_at"],
            "volume_at_last_label": row["volume_at_last_label"] or 0,
            "centroid": np.array(_parse_pgvector(row["centroid"])),
            "prev_ids": {str(a) for a in (row["prev_article_ids"] or [])},
        })
    return candidates


def _resolve_identities(
    sub_theme_data: list[_SubThemeData],
    candidates: list[dict],
    settings: Any,
) -> dict[int, dict]:
    """
    Assign each cluster at most one existing sub-theme, globally.

    Replaces a greedy loop that queried the single nearest centroid per cluster
    (LIMIT 1) and handed identities out first-come-first-served. Two clusters
    matching the same sub-theme meant the runner-up was force-merged into the
    winner — even when it was a strong match for a DIFFERENT, unclaimed
    sub-theme that it never got to see, because LIMIT 1 hid its second choice.
    Two distinct stories were fused as a result.

    The Hungarian algorithm maximises the total score across all pairs at once,
    so a cluster that loses its first choice can still take its second. Clusters
    left unassigned fall back to the old merge ONLY when their best candidate
    was genuinely taken by a stronger claim; otherwise they become new stories.
    """
    mapping: dict[int, dict] = {}
    live = [(i, st) for i, st in enumerate(sub_theme_data)
            if st.sub_theme_id != "__merged__"]

    if not live or not candidates:
        return mapping

    # Score every (cluster, sub-theme) pair.
    scores = np.zeros((len(live), len(candidates)))
    for r, (_, st) in enumerate(live):
        cluster_ids = {a.id for a in st.members}
        for c, cand in enumerate(candidates):
            scores[r, c] = identity_score(
                jaccard=_jaccard(cluster_ids, cand["prev_ids"]),
                cosine=_cosine_similarity(st.centroid, cand["centroid"]),
                jaccard_threshold=settings.subtheme_jaccard_match_threshold,
                centroid_threshold=settings.subtheme_centroid_match_threshold,
                drift_floor=settings.subtheme_drift_floor,
            )

    # linear_sum_assignment minimises, so negate to maximise.
    rows, cols = linear_sum_assignment(-scores)

    claimed_by: dict[int, int] = {}   # candidate index -> cluster row index
    for r, c in zip(rows, cols):
        if scores[r, c] <= 0:
            continue                  # no viable claim — leave the cluster new
        cluster_idx = live[r][0]
        mapping[cluster_idx] = {**candidates[c], "score": float(scores[r, c])}
        claimed_by[c] = r
        logger.info(
            "  [IDENTITY] Cluster %d -> '%s' (score %.3f)",
            cluster_idx, candidates[c]["db_label"] or candidates[c]["db_id"][:8],
            scores[r, c],
        )

    # Unassigned clusters whose best candidate was taken: fold them into the
    # winner rather than spawning a duplicate of a story that already exists.
    for r, (cluster_idx, st) in enumerate(live):
        if cluster_idx in mapping:
            continue
        best_c = int(np.argmax(scores[r]))
        if scores[r, best_c] <= 0 or best_c not in claimed_by:
            continue                  # genuinely new, or nothing worth merging into

        winner_idx = live[claimed_by[best_c]][0]
        winner = sub_theme_data[winner_idx]
        winner.members.extend(st.members)
        winner.reddit_post_ids.extend(st.reddit_post_ids)
        winner.reddit_post_count += st.reddit_post_count
        st.members = []
        st.reddit_post_ids = []
        st.reddit_post_count = 0
        st.sub_theme_id = "__merged__"   # sentinel so persistence skips it
        logger.info(
            "  [IDENTITY] Cluster %d (score %.3f) merged into cluster %d — "
            "same story split by HDBSCAN.",
            cluster_idx, scores[r, best_c], winner_idx,
        )

    return mapping


def _step4_label(
    cur: Any,
    topic_id: str,
    topic_name: str,
    sub_theme_data: list[_SubThemeData],
    groq_client: Groq,
    settings: Any,
) -> None:
    """
    Step 4: Identity resolution, loser-merge, and LLM labeling.
    - Phase 1: Propose matches (each cluster finds its best DB candidate)
    - Phase 2: Winner-takes-all conflict resolution; losers' members merged into winner
    - Phase 3: Relabeling decision vs volume_at_last_label (not last snapshot)
    - Phase 4: LLM call if relabeling is needed
    """
    relabel_threshold = settings.subtheme_relabel_volume_change_threshold

    # --- Phase 1 & 2: Identity resolution ---
    candidates = _load_identity_candidates(cur, topic_id)
    cluster_mapping = _resolve_identities(sub_theme_data, candidates, settings)

    # --- Phase 2.5: Prune loose members ---
    # Runs after the merge (so members are on their final cluster) and before
    # Phase 3 reads volume. From this point on, st.volume is the single number
    # every downstream step measures — relabeling, evolution and persistence.
    _prune_low_similarity_members(sub_theme_data, settings)

    # --- Phase 3: Apply Mapping and Decide Relabeling ---
    for i, st in enumerate(sub_theme_data):
        # Skip merged losers
        if st.sub_theme_id == "__merged__":
            continue

        current_volume = st.volume
        match = cluster_mapping.get(i)

        if not match:
            st.is_new = True
            st.sub_theme_id = None
            st.should_relabel = True
            logger.info("  [LABEL] Cluster %d: New story detected.", i)
        else:
            st.is_new = False
            st.sub_theme_id = match["db_id"]
            st.label_text = match["db_label"]
            st.description_text = match["db_description"]

            # Relabeling: compare against volume when label was LAST GENERATED
            # (not the most recent snapshot — prevents churn on small fluctuations)
            volume_at_last_label = match["volume_at_last_label"]
            growth = 0.0
            if volume_at_last_label > 0:
                growth = (current_volume - volume_at_last_label) / volume_at_last_label

            was_never_labeled = match["db_label_generated_at"] is None
            growth_spike = growth >= relabel_threshold

            st.should_relabel = was_never_labeled or growth_spike

            if growth_spike:
                logger.info(
                    "  [LABEL] Growth spike (%.1f%% vs label-time volume %d). Relabeling '%s'.",
                    growth * 100, volume_at_last_label, st.label_text,
                )
            elif not st.should_relabel:
                logger.info(
                    "  [LABEL] Retaining '%s' (growth %.1f%% from label-time vol %d).",
                    st.label_text, growth * 100, volume_at_last_label,
                )

    # --- Phase 4: LLM Labeling for clusters that need it ---
    for st in sub_theme_data:
        if st.sub_theme_id == "__merged__":
            continue
        if not st.should_relabel:
            continue

        sample_comments = []
        if st.reddit_post_ids:
            cur.execute("""
                SELECT body FROM reddit_comments
                WHERE article_id IN %s
                ORDER BY score DESC LIMIT 10
            """, (tuple(st.reddit_post_ids),))
            sample_comments = [r["body"] for r in cur.fetchall()]

        new_label, new_desc = _call_groq_label(
            groq_client=groq_client,
            topic_name=topic_name,
            keywords=st.keywords,
            sample_headlines=[a.headline for a in st.members],
            article_count=len(st.members),
            reddit_count=st.reddit_post_count,
            sentiment_score=st.sentiment_score,
            sample_comments=sample_comments,
        )
        if new_label:
            st.label_text = new_label
            st.description_text = new_desc



