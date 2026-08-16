// API payload shapes returned by the FastAPI backend.

export interface UserProfile {
  id: string;
  name: string;
  email: string;
  phone_number: string | null;
  created_at: string;
}

export interface Alert {
  id: string;
  article_id?: string;
  headline: string;
  summary: string | null;
  source_name: string;
  topic_name?: string;
  topic_id?: string;
  url: string;
  image_url?: string | null;
  relevance_score: number | null;
  created_at?: string;
  published_at?: string;
  membership_type?: "news" | "reddit";
  similarity_to_centroid?: number;
}

export interface Paginated<T> {
  data: T[];
  total_count: number;
}

export interface Topic {
  id: string;
  name: string;
  description: string | null;
  sensitivity: "broad" | "balanced" | "high";
  is_active: boolean;
  created_at?: string;
}

export type DeliveryChannel = "websocket" | "email" | "sms";

export interface SubTheme {
  id: string;
  label: string;
  description: string | null;
  /** new | growing | steady | declining | dormant | revival | rejected.
   *  The single source of truth — badges and chips derive from this. */
  status: string;
  sentiment_score: number | null; // -1..1
  total_volume: number;
  /** Fraction vs the previous run. null where no baseline exists (new/revival),
   *  rather than a fabricated number. */
  growth_pct: number | null;
  /** Previous run's volume; null on the first snapshot. */
  prev_volume?: number | null;
  /** Timestamp of the run this object describes. */
  snapshot_at?: string | null;
  /** @deprecated derive from `status` instead — kept for legacy payloads. */
  is_new?: boolean;
  /** @deprecated derive from `status` instead — kept for legacy payloads. */
  is_revival?: boolean;
  representative_article?: {
    headline: string;
    url: string;
    image_url?: string | null;
    source_name?: string;
    published_at?: string;
  } | null;
}

export interface TopicIntelligence {
  topic_name: string;
  topic_description: string | null;
  sensitivity: string;
  sub_themes: SubTheme[];
}

export interface HistoryTimestamp {
  ts: string;
  has_images: boolean;
}

export interface TimelineSnapshot {
  snapshot_at: string;
  total_volume: number;
  sentiment_score: number | null;
  growth_pct?: number | null;
}

export interface RedditComment {
  id: string;
  body: string;
  score: number;
  sentiment_score: number | null;
}

export interface DiscoveryStatus {
  status: string;
  progress?: number;
  message?: string;
}

// ── Admin ────────────────────────────────────────────────────────────

export interface AdminUser {
  id: string;
  name: string;
  email: string;
  topic_count: number;
}

export interface AdminTopic {
  id: string;
  name: string;
  sensitivity: string;
}

export interface AdminSubTheme {
  id: string;
  label: string;
  status: string;
  total_volume: number | null;
  topic?: string;
}

export interface PipelineRow {
  status: string | null;
  total: number;
  has_summary: number;
}

export interface SourceStat {
  source: string;
  type: string;
  total: number;
  last_24h: number;
  last_1h: number;
}

export interface AdminArticle {
  id: string;
  headline: string;
  url: string;
  source_name: string;
  summary: string | null;
  pipeline_status: string;
  published_at?: string;
  crawled_at?: string;
  topics?: string[];
}

export interface AdminArticles {
  total_count: number;
  articles: AdminArticle[];
}

export interface IngestionSource {
  id: string;
  name: string;
  type: string;
  is_active: boolean;
  poll_interval: number; // seconds
  articles_per_crawl: number | null;
}

export interface SourceFeed {
  id: string;
  feed_label: string;
  feed_url: string;
  is_active: boolean;
}

export interface Subreddit {
  id: string;
  name: string;
  sort: string;
  limit_per_crawl: number;
  is_active: boolean;
}

export interface SystemSetting {
  key: string;
  // boolean covers the kill switches; system_settings holds raw JSONB, so a
  // value can legitimately arrive as any of these three.
  value: number | string | boolean;
  description: string | null;
}
