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
) -> tuple[str | None, str | None]:
    """
    Call Groq to generate a sub-theme label + description.
    """
    prompt = f"""You are an expert news analyst and headline writer. Your task is to identify and label a specific emerging sub-theme within a broader topic.

BROADER TOPIC: {topic_name}
SUB-THEME KEYWORDS: {", ".join(keywords)}
SAMPLE HEADLINES:
{chr(10).join(f"- {h}" for h in sample_headlines[:10])}

VOLUME: {article_count} articles, {reddit_count} Reddit posts
SENTIMENT: {f"{sentiment_score:+.2f}" if sentiment_score is not None else "N/A"}

TASK:
1. Generate a specific, catchy, and professional LABEL (3-7 words).
   - BAD: "Global AI trends and job markets", "AI developments in workplace"
   - GOOD: "Jobs Affected due to AI", "The Shift to AI-Native Roles", "AI-Driven Workforce Disruption"
   - DO NOT include the word "Sub-theme" or "Theme" in the label.

2. Generate a 1-3 sentence DESCRIPTION.
   - CRITICAL: DO NOT start with "This sub-theme describes about...", "This cluster is about...", or any similar preamble.
   - START DIRECTLY with the core facts or trends.
   - BAD: "This sub theme describes about how AI is impacting the job market in 2024."
   - GOOD: "Widespread integration of generative AI is restructuring entry-level roles across the tech sector, leading to significant hiring freezes."

Return ONLY a JSON object with keys "label" and "description". No other text."""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.choices[0].message.content.strip()
            result = json.loads(content)
            return result.get("label"), result.get("description")
        except Exception as exc:
            logger.warning("Groq labeling attempt %d/%d failed: %s", attempt + 1, max_retries, exc)
            if attempt == max_retries - 1:
                logger.error("Groq labeling permanently failed for topic %s — storing without label", topic_name)
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
    Step 4: LLM labeling (LLama 3.1 via Groq).
    """
    relabel_threshold = settings.subtheme_relabel_volume_change_threshold

    for st in sub_theme_data:
        centroid_vec = _to_pgvector(st.centroid)
        article_count = len(st.members)
        current_volume = article_count + st.reddit_post_count

        cur.execute("""
            SELECT st.id,
                   st.label,
                   st.description,
                   st.label_generated_at,
                   (SELECT total_volume FROM sub_theme_snapshots
                    WHERE sub_theme_id = st.id
                    ORDER BY snapshot_at DESC LIMIT 1) AS last_volume
            FROM sub_themes st
            WHERE st.topic_id = %s
              AND 1 - (st.centroid <=> %s::vector) >= %s
            ORDER BY st.centroid <=> %s::vector
            LIMIT 1
        """, (topic_id, centroid_vec, settings.subtheme_centroid_match_threshold, centroid_vec))
        existing = cur.fetchone()

        if existing is None:
            st.is_new = True
            st.sub_theme_id = None
            st.should_relabel = True
            logger.info("  [MATCH] No existing sub-theme found. Creating new cluster.")
        else:
            st.is_new = False
            st.sub_theme_id = str(existing["id"])
            st.label_text = existing["label"]
            st.description_text = existing["description"]
            
            # Rule: If a cluster already exists and only its volume increases, its label must not change.
            # We only relabel if it was never labeled before.
            st.should_relabel = (existing["label_generated_at"] is None)
            
            if st.should_relabel:
                logger.info("  [MATCH] Found existing sub-theme '%s' but it needs initial labeling.", st.sub_theme_id)
            else:
                logger.info("  [MATCH] Retaining existing label for sub-theme '%s': '%s'", 
                            st.sub_theme_id, st.label_text)

        if st.should_relabel:
            new_label, new_desc = _call_groq_label(
                groq_client=groq_client,
                topic_name=topic_name,
                keywords=st.keywords,
                sample_headlines=[a.headline for a in st.members],
                article_count=article_count,
                reddit_count=st.reddit_post_count,
                sentiment_score=st.sentiment_score,
            )
            st.label_text = new_label
            st.description_text = new_desc
