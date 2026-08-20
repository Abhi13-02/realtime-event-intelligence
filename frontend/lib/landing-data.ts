// Public data source for the landing page. Server-only.
//
// The landing page is unauthenticated, but every backend route requires a
// bearer token. Rather than opening new public surface on FastAPI, this signs
// in as the demo account *server-side* and returns a trimmed, read-only
// projection. The demo credentials are already published on the login screen,
// so nothing new is exposed — and they never reach the browser from here.
//
// Two caches keep visitor traffic off the backend: the demo JWT is reused
// until it nears expiry, and the payload itself is memoised for a few seconds.
// Both are per-instance and in-memory, which is the right scope for something
// this cheap to rebuild.

// Server-only: reads DEMO_PASSWORD and holds a backend token in module scope.
// Never import this from a "use client" file.
import type {
  LandingFeed,
  LandingNarrative,
  LandingWireItem,
} from "@/lib/types";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000/v1";
const DEMO_EMAIL = process.env.DEMO_EMAIL ?? "demo@abhinavdev.online";
const DEMO_PASSWORD = process.env.DEMO_PASSWORD ?? "DemoPass123";

const ARTICLE_LIMIT = 40;
const TOPIC_LIMIT = 4;
const NARRATIVE_LIMIT = 6;
const PAYLOAD_TTL_MS = 15_000;
const FAILURE_TTL_MS = 5_000;
const TOKEN_TTL_MS = 45 * 60_000;
const UPSTREAM_TIMEOUT_MS = 6_000;

export const EMPTY_FEED: LandingFeed = {
  live: false,
  articles: [],
  narratives: [],
  matchedTotal: 0,
};

let cachedToken: { value: string; expiresAt: number } | null = null;
let cachedPayload: { value: LandingFeed; expiresAt: number } | null = null;

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T | null> {
  try {
    const res = await fetch(`${BACKEND_URL}${path}`, {
      ...init,
      cache: "no-store",
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    // unreachable backend, timeout, or malformed body — callers degrade
    return null;
  }
}

async function demoToken(): Promise<string | null> {
  if (cachedToken && cachedToken.expiresAt > Date.now()) return cachedToken.value;

  const body = await fetchJson<{ access_token: string }>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: DEMO_EMAIL, password: DEMO_PASSWORD }),
  });
  if (!body?.access_token) return null;

  cachedToken = { value: body.access_token, expiresAt: Date.now() + TOKEN_TTL_MS };
  return cachedToken.value;
}

/** Backend shapes, narrowed to only the fields the landing page reads. */
interface RawAlert {
  id: string;
  article_id?: string;
  headline: string;
  summary: string | null;
  source_name: string;
  topic_name?: string;
  url: string;
  relevance_score: number | null;
  published_at?: string;
  created_at?: string;
  membership_type?: "news" | "reddit";
  similarity_to_centroid?: number;
}

interface RawSubTheme {
  id: string;
  label: string;
  description: string | null;
  status: string;
  total_volume: number;
  growth_pct: number | null;
  representative_article?: {
    headline: string;
    source_name?: string;
    url: string;
  } | null;
}

/**
 * Reddit is no longer an ingestion source, but historical rows are still in
 * the database and would surface a subreddit name on a public page. Both
 * checks matter: membership_type catches rows tagged at ingest, the name
 * pattern catches anything tagged differently (source "Reddit", "r/news").
 */
function isReddit(a: { membership_type?: string; source_name?: string }): boolean {
  if (a.membership_type === "reddit") return true;
  return /(^|\W)(reddit|r\/)/i.test(a.source_name ?? "");
}

function toWireItem(a: RawAlert): LandingWireItem {
  // The match score the pipeline actually computed. Alerts carry either the
  // topic relevance or the distance to a narrative centroid depending on how
  // they were routed; prefer the former, fall back to the latter.
  const score = a.relevance_score ?? a.similarity_to_centroid ?? null;
  return {
    id: a.id,
    // Short identity key — stands in for the dedup fingerprint at the gate.
    key: (a.article_id ?? a.id).replace(/-/g, "").slice(0, 8),
    headline: a.headline,
    source: a.source_name,
    topic: a.topic_name ?? null,
    url: a.url,
    score,
    hasSummary: Boolean(a.summary),
    at: a.published_at ?? a.created_at ?? null,
  };
}

function toNarrative(n: RawSubTheme, topic: string): LandingNarrative {
  return {
    id: n.id,
    label: n.label,
    description: n.description,
    status: n.status,
    volume: n.total_volume,
    growth: n.growth_pct,
    topic,
    // A cluster's lead article can still be an old Reddit row. Keep the
    // headline, drop the attribution rather than name the source.
    lead: n.representative_article
      ? {
          headline: n.representative_article.headline,
          source: isReddit(n.representative_article)
            ? null
            : (n.representative_article.source_name ?? null),
        }
      : null,
  };
}

async function build(): Promise<LandingFeed> {
  const token = await demoToken();
  if (!token) return EMPTY_FEED;
  const authed = { headers: { Authorization: `Bearer ${token}` } };

  // Independent calls, so they run together: this sits in front of the
  // landing page's first paint, and chaining them would stack their timeouts
  // on top of each other whenever the backend is slow.
  const [alerts, topics] = await Promise.all([
    fetchJson<{ data: RawAlert[]; total_count: number }>(
      `/alerts?page=1&limit=${ARTICLE_LIMIT}`,
      authed,
    ),
    // Narratives live per-topic, so this is a fan-out. Capped at a handful of
    // topics — the page only ever renders NARRATIVE_LIMIT of them.
    fetchJson<{ data: { id: string; name: string }[] }>(
      `/topics?page=1&limit=${TOPIC_LIMIT}`,
      authed,
    ),
  ]);

  const narratives: LandingNarrative[] = [];
  if (topics?.data?.length) {
    const results = await Promise.all(
      topics.data.map((t) =>
        fetchJson<{ sub_themes: RawSubTheme[] }>(
          `/topics/${t.id}/intelligence`,
          authed,
        ).then((r) => ({ topic: t.name, subThemes: r?.sub_themes ?? [] })),
      ),
    );
    for (const { topic, subThemes } of results) {
      for (const st of subThemes) {
        if (st.status === "rejected" || st.status === "dormant") continue;
        narratives.push(toNarrative(st, topic));
      }
    }
  }

  // Surface the clusters that are actually moving: new and growing first,
  // then by size. Six steady clusters would prove nothing.
  const rank = (s: string) =>
    s === "new" ? 0 : s === "revival" ? 1 : s === "growing" ? 2 : 3;
  narratives.sort((a, b) => rank(a.status) - rank(b.status) || b.volume - a.volume);

  const articles = (alerts?.data ?? []).filter((a) => !isReddit(a)).map(toWireItem);

  return {
    live: articles.length > 0,
    articles,
    narratives: narratives.slice(0, NARRATIVE_LIMIT),
    matchedTotal: alerts?.total_count ?? 0,
  };
}

export async function getLandingFeed(): Promise<LandingFeed> {
  if (cachedPayload && cachedPayload.expiresAt > Date.now()) {
    return cachedPayload.value;
  }

  const payload = await build();

  // A good payload is held for the full window. A failed one is held only
  // briefly: long enough that a backend outage can't make every single
  // visitor sit through the upstream timeouts, short enough that the page
  // recovers within seconds of the backend coming back.
  cachedPayload = {
    value: payload,
    expiresAt: Date.now() + (payload.live ? PAYLOAD_TTL_MS : FAILURE_TTL_MS),
  };
  return payload;
}
