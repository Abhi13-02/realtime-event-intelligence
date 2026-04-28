import json
import logging
from typing import Any
from groq import Groq
from .models import _SubThemeData, _to_pgvector

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
    match_threshold = settings.subtheme_centroid_match_threshold

    # --- Phase 1: Proposals ---
    proposals = []
    for i, st in enumerate(sub_theme_data):
        centroid_vec = _to_pgvector(st.centroid)
        cur.execute("""
            SELECT st.id,
                   st.label,
                   st.description,
                   st.label_generated_at,
                   st.volume_at_last_label,
                   1 - (st.centroid <=> %(centroid)s::vector) AS similarity
            FROM sub_themes st
            WHERE st.topic_id = %(topic_id)s
              AND 1 - (st.centroid <=> %(centroid)s::vector) >= %(threshold)s
            ORDER BY st.centroid <=> %(centroid)s::vector
            LIMIT 1
        """, {
            "centroid": centroid_vec,
            "topic_id": topic_id,
            "threshold": match_threshold
        })
        match = cur.fetchone()

        if match:
            proposals.append({
                "cluster_idx": i,
                "db_id": str(match["id"]),
                "similarity": float(match["similarity"]),
                "db_label": match["label"],
                "db_description": match["description"],
                "db_label_generated_at": match["label_generated_at"],
                "volume_at_last_label": match["volume_at_last_label"] or 0,
            })

    # --- Phase 2: Conflict Resolution with Loser-Merge ---
    # Sort by similarity DESC so the best-matching cluster wins the ID
    proposals.sort(key=lambda x: x["similarity"], reverse=True)

    assigned_db_ids: dict[str, int] = {}  # db_id -> winning cluster_idx
    cluster_mapping: dict[int, dict] = {}

    for prop in proposals:
        db_id = prop["db_id"]
        if db_id not in assigned_db_ids:
            # Winner: takes the ID
            cluster_mapping[prop["cluster_idx"]] = prop
            assigned_db_ids[db_id] = prop["cluster_idx"]
        else:
            # Loser: merge its members into the winner
            winner_idx = assigned_db_ids[db_id]
            winner_st = sub_theme_data[winner_idx]
            loser_st = sub_theme_data[prop["cluster_idx"]]
            winner_st.members.extend(loser_st.members)
            winner_st.reddit_post_ids.extend(loser_st.reddit_post_ids)
            winner_st.reddit_post_count += loser_st.reddit_post_count
            # Mark loser as merged (empty it out so persistence skips it)
            loser_st.members = []
            loser_st.reddit_post_ids = []
            loser_st.reddit_post_count = 0
            loser_st.sub_theme_id = "__merged__"  # sentinel so persistence skips
            logger.info(
                "  [LABEL] Identity conflict: Cluster %d (sim=%.4f) merged into Cluster %d (winner of ID %s).",
                prop["cluster_idx"], prop["similarity"], winner_idx, db_id,
            )

    # --- Phase 3: Apply Mapping and Decide Relabeling ---
    for i, st in enumerate(sub_theme_data):
        # Skip merged losers
        if st.sub_theme_id == "__merged__":
            continue

        current_volume = len(st.members) + st.reddit_post_count
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



