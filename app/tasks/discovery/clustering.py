import logging
from typing import Any
import numpy as np
import hdbscan
import umap
from .models import _ArticleRow, _SubThemeData, _cosine_similarity, _extract_keywords, _parse_pgvector

logger = logging.getLogger(__name__)

def _step1_cluster(
    articles: list[_ArticleRow],
    settings: Any,
) -> list[_SubThemeData]:
    """
    HDBSCAN clustering of news article embeddings (all non-Reddit sources).
    """
    embeddings = np.array([a.embedding for a in articles])

    n_components = min(getattr(settings, 'subtheme_umap_n_components', 10), len(articles) - 1)
    reduced = umap.UMAP(
        n_components=n_components,
        n_neighbors=min(15, len(articles) - 1),
        min_dist=0.0,
        metric="cosine",
        random_state=42,
    ).fit_transform(embeddings)

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=settings.subtheme_min_cluster_size,
        min_samples=settings.subtheme_min_samples,
        metric="euclidean",
        cluster_selection_method=settings.subtheme_cluster_selection_method,
    )
    labels = clusterer.fit_predict(reduced)

    raw_clusters: dict[int, list[_ArticleRow]] = {}
    for i, label in enumerate(labels):
        if label == -1:
            continue
        raw_clusters.setdefault(label, []).append(articles[i])

    result: list[_SubThemeData] = []

    for label, members in raw_clusters.items():
        member_embeddings = np.array([a.embedding for a in members])
        centroid = member_embeddings.mean(axis=0)

        sims = [_cosine_similarity(a.embedding, centroid) for a in members]
        sorted_indices = np.argsort(sims)[::-1]
        
        representative = members[int(sorted_indices[0])]
        anchors = [members[int(i)].embedding for i in sorted_indices[:3]]

        keywords = _extract_keywords([a.headline for a in members], top_n=10)

        sub_theme = _SubThemeData(label=label)
        sub_theme.members = members
        sub_theme.centroid = centroid
        sub_theme.anchor_embeddings = anchors
        sub_theme.representative_article_id = representative.id
        sub_theme.keywords = keywords
        result.append(sub_theme)

    return result

def _step2_assign_reddit(
    cur: Any,
    conn: Any,
    topic_id: str,
    sub_theme_data: list[_SubThemeData],
    settings: Any,
) -> None:
    """
    Assign Reddit posts to their nearest existing sub-theme centroid using pgvector ANN.
    """
    cur.execute("""
        SELECT a.id, a.embedding::text
        FROM article_topic_matches atm
        JOIN articles a ON atm.article_id = a.id
        JOIN sources  s ON a.source_id    = s.id
        WHERE atm.topic_id  = %s
          AND s.type        = 'reddit'
          AND a.crawled_at  >= NOW() - INTERVAL '%s days'
          AND a.embedding IS NOT NULL
    """, (topic_id, settings.subtheme_window_days))
    reddit_rows = cur.fetchall()

    if not reddit_rows:
        logger.info("[REDDIT-ASSIGN] topic=%s: no Reddit posts in window.", topic_id)
        return

    threshold = settings.subtheme_reddit_assign_threshold
    logger.info(
        "[REDDIT-ASSIGN] topic=%s: evaluating %d Reddit posts against %d centroids (threshold=%.2f)",
        topic_id, len(reddit_rows), len(sub_theme_data), threshold,
    )

    post_ids_list = [str(r["id"]) for r in reddit_rows]
    cur.execute("SELECT id, headline FROM articles WHERE id = ANY(%s::uuid[])", (post_ids_list,))
    headline_by_id = {str(r["id"]): (r["headline"] or "")[:80] for r in cur.fetchall()}

    assigned = 0
    for reddit_row in reddit_rows:
        post_id = str(reddit_row["id"])
        post_embedding = np.array(_parse_pgvector(reddit_row["embedding"]))

        best_sim = -1.0
        best_idx = -1
        for idx, st in enumerate(sub_theme_data):
            points = []
            if st.centroid is not None:
                points.append(st.centroid)
            points.extend(st.anchor_embeddings)

            if not points:
                continue

            cluster_max_sim = max(_cosine_similarity(post_embedding, p) for p in points)
            
            if cluster_max_sim > best_sim:
                best_sim = cluster_max_sim
                best_idx = idx

        best_label = sub_theme_data[best_idx].label if best_idx >= 0 else "<none>"
        headline = headline_by_id.get(post_id, "<unknown>")

        if best_idx >= 0 and best_sim >= threshold:
            sub_theme_data[best_idx].reddit_post_ids.append(post_id)
            sub_theme_data[best_idx].reddit_post_count += 1
            assigned += 1
            logger.info(
                "  [ASSIGN] sim=%.4f >= %.2f | '%s' -> sub-theme '%s' (total: %d)",
                best_sim, threshold, headline, best_label, len(sub_theme_data[best_idx].reddit_post_ids)
            )
        else:
            logger.info(
                "  [SKIP]   sim=%.4f < %.2f | '%s' (nearest: '%s')",
                best_sim, threshold, headline, best_label,
            )

    logger.info(
        "[REDDIT-ASSIGN] topic=%s: %d/%d posts assigned",
        topic_id, assigned, len(reddit_rows),
    )
