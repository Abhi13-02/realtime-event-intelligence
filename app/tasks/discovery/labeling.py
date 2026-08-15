import json
import logging
import re
import time
from typing import Any

import numpy as np
from groq import Groq
from scipy.optimize import linear_sum_assignment

from app.config import get_settings

from .models import _SubThemeData, _cosine_similarity, _parse_pgvector
from .clustering import _prune_low_similarity_members

logger = logging.getLogger(__name__)

# How hard to push back on a loosely-related cluster, keyed to the topic's
# user-facing sensitivity setting. This is the only knob the user controls, so
# it is the natural place to express "how strict should the gate be".
_SENSITIVITY_RULES = {
    "broad": (
        "The user wants WIDE coverage. Mark a story irrelevant only if it is "
        "clearly about a different subject altogether. Tangential, adjacent or "
        "background stories should be kept."
    ),
    "balanced": (
        "The user wants the story to genuinely belong to this topic. Keep it if "
        "it is about the topic or a closely related aspect of it. Mark it "
        "irrelevant if the connection is only incidental — a passing mention, or "
        "a shared word that means something different here."
    ),
    "high": (
        "The user wants TIGHT coverage. Keep the story only if it is directly "
        "and substantially about this topic. Mark anything peripheral, adjacent "
        "or merely related-sounding as irrelevant."
    ),
}


# How many of a cluster's headlines the model gets to see, and how much of each.
# A cluster can hold hundreds of articles; the model sees at most this many, and
# smaller clusters send everything they have.
#
# Both numbers are a token budget, not a quality judgement. Groq's free tier caps
# tokens per day and per minute, and a run right after a database wipe asks for a
# fresh label for EVERY cluster at once — roughly 150 calls in a burst. At 20
# untruncated headlines that exhausted the 200k daily allowance and returned 429
# for 67 calls, each of which fails open and leaves a cluster with no label at
# all. Ten headlines capped at 100 characters is about a quarter of the tokens,
# and a truncated headline still carries its subject.
MAX_SAMPLE_HEADLINES = 10
HEADLINE_CHAR_LIMIT = 100

# Longest pause we will take waiting out a rate limit. Per-minute limits clear in
# seconds and are worth waiting for; a daily limit reports minutes or hours and
# no amount of waiting inside one task will clear it, so we stop instead.
MAX_BACKOFF_SECONDS = 30


def _retry_after_seconds(exc: Exception) -> float | None:
    """
    How long the provider asked us to wait, or None if it did not say.

    Prefers the Retry-After header and falls back to the wait embedded in Groq's
    429 text ("Please try again in 2m13.92s"), which is the only place the
    per-minute figure appears in some responses.
    """
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None)
    if headers:
        raw = headers.get("retry-after") or headers.get("Retry-After")
        if raw:
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass

    m = re.search(r"try again in\s+(?:(\d+)m)?([\d.]+)s", str(exc), re.IGNORECASE)
    if not m:
        return None
    minutes = float(m.group(1)) if m.group(1) else 0.0
    return minutes * 60.0 + float(m.group(2))


def _central_headlines(st: _SubThemeData, limit: int = MAX_SAMPLE_HEADLINES) -> list[str]:
    """
    The cluster's most representative headlines, nearest the centroid first.

    Previously the prompt took whatever order members happened to be in and
    sliced the first ten, so a large cluster could be judged entirely on its
    least typical articles — the model would see the fringe and rule on the
    whole story. Ranking by distance to the centroid means the sample now
    describes the cluster's core, and any stragglers land at the end where they
    read as outliers rather than as the subject.

    The similarity is the same one clustering already computes to choose the
    representative article, so this costs nothing extra.
    """
    if not st.members:
        return []
    if st.centroid is None:
        return [a.headline for a in st.members[:limit]]
    ranked = sorted(
        st.members,
        key=lambda a: _cosine_similarity(a.embedding, st.centroid),
        reverse=True,
    )
    return [a.headline for a in ranked[:limit]]


def _call_groq_label(
    groq_client: Groq,
    topic_name: str,
    topic_description: str | None,
    sensitivity: str,
    keywords: list[str],
    sample_headlines: list[str],
    article_count: int,
    reddit_count: int,
    sentiment_score: float | None,
    sample_comments: list[str] = None,
) -> tuple[str | None, str | None, bool]:
    """
    Ask Groq to label a cluster AND judge whether it belongs to the user's topic.

    Returns (label, description, relevant).

    WHY THE RELEVANCE JUDGEMENT LIVES HERE: topic matching upstream is embedding
    similarity against the topic vector, which is good at "is this the same
    broad subject" and poor at "is this the thing the user actually asked for".
    Occasionally enough loosely-related articles arrive together to form their
    own coherent cluster, and it surfaces on the dashboard as a narrative the
    user never wanted. This call already happens for exactly the clusters at
    risk — brand-new ones — so the judgement is free: one extra field on a
    request that was being made anyway.

    `relevant` defaults to True on ANY failure. A missing or malformed answer
    means we have no verdict, and "no verdict" must never be read as "delete".
    """
    comments_section = ""
    if sample_comments:
        comments_section = "\nPEOPLE'S VOICES (Top Reddit Comments):\n" + "\n".join(f"- {c[:200]}..." for c in sample_comments[:5])

    # The user's own words about what they want, when they gave any. Without
    # this the model is judging against a bare topic name like "Apple", which is
    # not enough to tell the company from the fruit.
    topic_context = f"\nWHAT THE USER WANTS FROM THIS TOPIC:\n{topic_description}" if topic_description else ""
    sensitivity_rule = _SENSITIVITY_RULES.get(sensitivity, _SENSITIVITY_RULES["balanced"])

    prompt = f"""You are an expert news analyst. Your task is to identify and label an emerging story within a broader topic.

BROADER TOPIC: {topic_name}{topic_context}
CORE KEYWORDS: {", ".join(keywords)}

REPRESENTATIVE HEADLINES (most central to the story first):
{chr(10).join(f"- {(h or '')[:HEADLINE_CHAR_LIMIT]}" for h in sample_headlines[:MAX_SAMPLE_HEADLINES])}
{comments_section}

METRICS: {article_count} news reports, {reddit_count} social discussions.
SENTIMENT: {f"{sentiment_score:+.2f}" if sentiment_score is not None else "N/A"}

TASK:
1. Decide RELEVANCE. Do these headlines, taken together, form a story that
   belongs under the topic described above?
   - {sensitivity_rule}
   - Judge the story as a WHOLE, by what the MAJORITY of these headlines are
     about. The list is ordered with the most central headlines first, so weigh
     the ones at the top most heavily.
   - Clusters are built automatically and ALWAYS carry a few stragglers. Two or
     three odd headlines is normal and expected — it is NOT a reason to call the
     story irrelevant. Reject only when the headlines as a body are about a
     different subject, not when a handful of them are.
   - When genuinely unsure, answer true. Keeping a borderline story is a much
     smaller mistake than hiding one the user wanted.

2. Generate a LABEL (3-7 words).
   - Use SIMPLE, PLAIN ENGLISH that anyone on the street would understand.
   - NO JARGON. NO corporate speak.
   - Dont keep it general , it should be specific to the story.
   - GOOD: "People worried about AI taking jobs", "Google's big gamble on AI agents"
   - BAD: "Generative AI workforce integration trends"

3. Generate a 1-3 sentence DESCRIPTION.
   - Start directly with the facts.
   - Use simple language.
   - If the "PEOPLE'S VOICES" show a clear pattern (e.g., people are angry, scared, or excited), mention what people are saying.
   - EXAMPLE: "Major tech companies are replacing entry-level staff with AI tools. On social media, workers are expressing deep fear about their career futures and calling for new labor protections."

Return ONLY a JSON object with keys "relevant" (boolean), "label" and "description"."""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = groq_client.chat.completions.create(
                model=get_settings().groq_model,
                messages=[{"role": "user", "content": prompt}],
                # Deterministic: this is a classification, and the default of 1.0
                # would let the same cluster be judged differently run to run.
                temperature=0,
            )
            content = response.choices[0].message.content.strip()
            # Handle possible markdown blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            result = json.loads(content)
            # Anything other than an explicit false is treated as relevant —
            # a missing key, a string, a null all fail open.
            relevant = result.get("relevant", True) is not False
            return result.get("label"), result.get("description"), relevant
        except Exception as exc:
            logger.warning("Groq labeling attempt %d/%d failed: %s", attempt + 1, max_retries, exc)
            if attempt == max_retries - 1:
                return None, None, True

            # Rate limits were being retried three times inside ~150ms while the
            # provider was explicitly saying "try again in 9.8s", so all three
            # attempts failed on the same exhausted budget and the cluster came
            # back unlabelled. Wait the time we are actually told to wait.
            wait = _retry_after_seconds(exc)
            if wait is None:
                continue
            if wait > MAX_BACKOFF_SECONDS:
                # A wait this long is the daily budget, not the per-minute one.
                # No number of retries recovers it, and each attempt still costs
                # a request, so stop and let the caller fail open.
                logger.warning(
                    "Groq asks for %.0fs — beyond the %ds budget, giving up on this cluster.",
                    wait, MAX_BACKOFF_SECONDS,
                )
                return None, None, True
            logger.info("Rate limited; waiting %.1fs before retry.", wait)
            time.sleep(wait)
    return None, None, True

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

    Dormant ones are included — a story returning from silence should reclaim
    its own identity rather than appear as a stranger.

    REJECTED ones are included too, which looks wrong but is the point: a
    cluster the relevance gate has already thrown out will be rebuilt by HDBSCAN
    on every subsequent run, because its articles are still sitting in the
    window. Matching it against the rejected row lets step 4 recognise it and
    drop it silently, with no second LLM call and no chance of the model
    answering differently the second time. Excluding them here would mean
    re-asking about the same rejected cluster on every run forever.
    """
    cur.execute("""
        SELECT st.id,
               st.label,
               st.description,
               st.label_generated_at,
               st.volume_at_last_label,
               st.status,
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
    """, (topic_id,))

    candidates = []
    for row in cur.fetchall():
        candidates.append({
            "db_id": str(row["id"]),
            "db_label": row["label"],
            "db_description": row["description"],
            "db_label_generated_at": row["label_generated_at"],
            "volume_at_last_label": row["volume_at_last_label"] or 0,
            "db_status": row["status"],
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
    topic_description: str | None = None,
    sensitivity: str = "balanced",
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

        if match and match["db_status"] == "rejected":
            # This cluster was already judged off-topic on an earlier run and
            # has simply been rebuilt from articles still sitting in the window.
            # Recognise it and drop it without asking the model again — that
            # keeps the verdict stable instead of letting it flip run to run.
            st.is_new = False
            st.is_rejected = True
            st.sub_theme_id = match["db_id"]
            st.should_relabel = False
            logger.info(
                "  [GATE] Cluster %d matches previously rejected story '%s' — skipping.",
                i, (match["db_label"] or match["db_id"][:8]),
            )
            continue

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
            # Carried to the gate. A cluster whose labelling call failed on an
            # earlier run is not an established narrative — it has never been
            # named or judged, and since unlabelled clusters are hidden from the
            # dashboard the user has never seen it either.
            st.never_judged = was_never_labeled

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

    # --- Phase 4: LLM labeling + relevance gate ---
    for st in sub_theme_data:
        if st.sub_theme_id == "__merged__" or st.is_rejected:
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

        new_label, new_desc, relevant = _call_groq_label(
            groq_client=groq_client,
            topic_name=topic_name,
            topic_description=topic_description,
            sensitivity=sensitivity,
            keywords=st.keywords,
            sample_headlines=_central_headlines(st),
            article_count=len(st.members),
            reddit_count=st.reddit_post_count,
            sentiment_score=st.sentiment_score,
            sample_comments=sample_comments,
        )

        # THE GATE — applied to clusters that have never been judged.
        #
        # That means brand-new clusters, and also clusters whose labelling call
        # failed on an earlier run. The second case used to slip through and it
        # created a permanent immunity: fail-open kept the unjudged cluster, and
        # by the time a later run could actually reach the model, the cluster was
        # no longer "new", so a clear verdict of off-topic could not be acted on.
        # Two Bollywood clusters born during a rate-limit window survived exactly
        # this way and sat on the dashboard labelled "No Bollywood content".
        # Neither had ever been named or shown under a real title, so there was
        # never anything to protect.
        #
        # A cluster that HAS been judged and named keeps its place. Deleting a
        # narrative the user has been watching, with its history, on the strength
        # of one model call is the failure this guard still prevents.
        if not relevant:
            if st.is_new or st.never_judged:
                st.is_rejected = True
                logger.info(
                    "  [GATE] Rejected %s cluster as off-topic (sensitivity=%s): %s",
                    "new" if st.is_new else "never-judged",
                    sensitivity, (new_label or st.keywords[:5]),
                )
            else:
                logger.info(
                    "  [GATE] '%s' judged off-topic but is an established story — keeping.",
                    st.label_text,
                )
                # Keep the wording it already had. When the model rejects a
                # cluster it writes a label describing the REFUSAL — "No
                # Bollywood content", "No relevant story" — and overwriting with
                # that put the model's verdict on the dashboard as if it were the
                # name of a narrative. The cluster survives here by policy, so it
                # keeps the name it earned when it was last judged on-topic.
                continue

        if new_label:
            st.label_text = new_label
            st.description_text = new_desc



