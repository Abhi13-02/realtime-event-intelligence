from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    All configuration is read from environment variables (your .env file).
    Pydantic validates types automatically — if DATABASE_URL is missing or
    SMTP_PORT is not a number, the app fails immediately on startup with a
    clear error instead of crashing later with a confusing AttributeError.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ───────────────────────────────────────────────────────────────
    admin_secret_key: str
    environment: str = "development"

    # ── Database ──────────────────────────────────────────────────────────
    database_url: str
    postgres_user: str
    postgres_password: str
    postgres_db: str

    # ── Redis ─────────────────────────────────────────────────────────────
    redis_url: str                          # db=0 — Celery broker
    websocket_redis_url: str                # db=1 — WebSocket tickets

    # ── Kafka ─────────────────────────────────────────────────────────────
    kafka_bootstrap_servers: str

    # ── Ingestion (Managed in DB) ─────────────────────────────────────────
    # Note: Polling intervals and crawl limits are now managed via the 
    # Admin Panel at runtime. Static .env overrides are deprecated.

    # ── Sensitivity thresholds (Managed in DB) ────────────────────────────
    # Sensitivity thresholds (broad, balanced, high) are now managed via the 
    # Admin Panel 'System Settings' at runtime. Static .env overrides are deprecated.

    # ── External APIs ─────────────────────────────────────────────────────
    groq_api_key: str
    # One name for every Groq call: summarisation, topic expansion and the
    # narrative labeling/relevance gate. It used to be hardcoded separately in
    # all three, which is why retiring llama-3.1-8b-instant meant editing code
    # in three files under a deadline. Overridable via GROQ_MODEL so the next
    # decommission notice is an env change and a restart.
    #
    # Chosen over llama-3.3-70b-versatile and gpt-oss-120b by measuring the
    # relevance gate on 12 clusters across 3 topics: this was the only model
    # with zero false KEEPS, and false keeps are the clutter that made the gate
    # look broken. See docs/low-level-design/intelligence-lld.md.
    groq_model: str = "openai/gpt-oss-20b"
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_from_number: str

    # ── Reddit ────────────────────────────────────────────────────────────
    reddit_client_id: str
    reddit_client_secret: str
    reddit_user_agent: str
    # Reddit subreddits are now managed in the 'reddit_subreddits' table.

    # ── Email ───────────────────────────────────────────────────────────────────
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    from_email: str

    # ── News API keys ─────────────────────────────────────────────────────
    newsapi_key: Optional[str] = None
    newsdata_key: Optional[str] = None
    guardian_key: Optional[str] = None

    # ── Intelligence layer (sub-theme discovery) ──────────────────────────
    # All thresholds configurable via env vars — nothing is hardcoded in tasks.
    # See docs/low-level-design/intelligence-lld.md Section 10 for full descriptions.
    subtheme_discovery_interval_hours: int        = 6
    subtheme_window_days: int                     = 3      # rolling window for all sources
    subtheme_min_articles: int                    = 5
    subtheme_min_cluster_size: int                = 5
    subtheme_min_samples: int                     = 1
    subtheme_cluster_selection_method: str        = "leaf"
    subtheme_umap_n_components: int               = 10     # UMAP dims before HDBSCAN (10 recommended for 768-dim embeddings)
    # DISABLED (0.0) after it destroyed granularity in production. Kept as a
    # wired-up knob because the mechanism is useful, but do not raise it without
    # re-measuring per topic at full corpus size.
    #
    # It merges clusters separated by less than this distance. It was set to 0.5
    # on evidence that turned out to be worthless, in three compounding ways:
    #
    #   1. Tuned on ONE topic (n=112) and applied to all. At n=618 the same
    #      value collapsed 46 clusters into 7, the largest holding 303 articles.
    #   2. Judged by a noise metric that cannot detect this failure. Noise is
    #      minimised by putting everything in one cluster, so "noise fell
    #      18.7% -> 2.6%" was measuring the damage and calling it success.
    #   3. Chosen against pairwise-distance percentiles (p5/median/p95). Epsilon
    #      is compared against condensed-tree merge heights, which are far
    #      smaller, so a value that looked "below the 5th percentile" and
    #      therefore harmless was in fact well above the merge scale.
    #
    # Downstream effect worth remembering: over-merged clusters are incoherent,
    # so the LLM relevance gate rejects them. A wave of rejections is a symptom
    # of bad clustering upstream, not a prompt that is too strict.
    #
    # Measured effect on Bollywood (n=618, leaf, mcs=5, ms=1):
    #   eps 0.0 -> 46 clusters (largest 34)   <- shipped
    #   eps 0.3 -> 27 clusters (largest 56)
    #   eps 0.5 ->  7 clusters (largest 303)
    #   eps 0.8 ->  2 clusters (largest 562)
    subtheme_cluster_selection_epsilon: float     = 0.0
    # ── Identity resolution ───────────────────────────────────────────
    # Calibrated against tests/benchmark_identity_stability.py. See
    # docs/discovery-accuracy-log.md v2 for the measurements behind each value.
    #
    # Membership overlap with the previous run is the PRIMARY signal. A story
    # reported with fresh articles keeps its identity because it keeps its
    # articles, not because its centroid happened to stay put.
    subtheme_jaccard_match_threshold: float       = 0.30
    # Frozen-centroid cosine, used only when there is no membership history to
    # compare against. Deliberately strict: different stories in the same topic
    # peak at 0.803, so 0.85 cannot cause a false merge. It WILL under-match a
    # story returning after a full window turnover — that is the safe direction.
    subtheme_centroid_match_threshold: float      = 0.85
    # Drift veto against the immutable creation-time centroid. Below this, the
    # cluster is forked even when article overlap is high, which is what stops a
    # chain of high-overlap runs slowly walking one narrative into another.
    # 0.60 sits under the healthy-story minimum after full turnover (0.703) so
    # it never fires on ordinary rotation, and over the different-story mean
    # (0.444) so it still fires on genuine change. The different-story MAXIMUM
    # of 0.803 is irrelevant here: the veto only ever splits, never merges.
    subtheme_drift_floor: float                   = 0.60
    subtheme_reddit_assign_threshold: float       = 0.55
    # Members below this cosine similarity to their own cluster centroid are
    # pruned before volume is measured. HDBSCAN occasionally sweeps loosely
    # related articles into a cluster; this is the guard that removes them.
    subtheme_member_similarity_threshold: float   = 0.60
    # Volume change vs the previous run that moves a cluster out of 'steady'.
    # Symmetric dead band: anything between -20% and +20% is run-to-run noise
    # and should not flip the chip. Lowered from 0.5 — at that level a story
    # could gain 40% and still be reported as unchanged.
    # (subtheme_disappearing_threshold was removed here: decay relative to the
    #  all-time peak is a different yardstick from the run-over-run delta, and
    #  mixing the two is what let a live 15-article cluster be ruled inactive.)
    subtheme_growing_threshold: float             = 0.20
    subtheme_declining_threshold: float           = 0.20
    subtheme_sentiment_shift_threshold: float     = 0.2
    subtheme_baseline_days: int                   = 7
    subtheme_relabel_volume_change_threshold: float = 0.50  # raised from 0.30; compared to volume at last label time


    # ── Auth (backend-owned credentials) ──────────────────────────────────
    # HS256 secret for signing/verifying access tokens issued by /v1/auth/login.
    # Generate with: python -c "import secrets; print(secrets.token_hex(32))"
    auth_jwt_secret: str
    auth_jwt_expiry_days: int = 7

    # ── Dev bypass ────────────────────────────────────────────────────────
    # Only active when environment=development. Set environment=production to disable.
    dev_user_id: str = "dev-test-user"


@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached Settings instance.

    @lru_cache means this function only reads and validates the .env file
    once — on the first call. Every subsequent call returns the same object
    from memory. This means:
      - No repeated disk I/O on every request
      - One consistent settings object shared across the entire app

    Usage in any file:
        from app.config import get_settings
        settings = get_settings()
        print(settings.database_url)
    """
    return Settings()
