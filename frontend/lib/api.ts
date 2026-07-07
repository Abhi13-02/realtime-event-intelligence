// Client-side API layer. All calls go through the Next.js server proxies
// (/api/backend/* for user routes, /api/admin/* for admin routes) so no
// token or admin key ever lives in browser JavaScript.

import type {
  Alert,
  AdminArticles,
  AdminSubTheme,
  AdminTopic,
  AdminUser,
  DeliveryChannel,
  DiscoveryStatus,
  HistoryTimestamp,
  IngestionSource,
  Paginated,
  PipelineRow,
  RedditComment,
  SourceFeed,
  SourceStat,
  Subreddit,
  SubTheme,
  SystemSetting,
  TimelineSnapshot,
  Topic,
  TopicIntelligence,
  UserProfile,
} from "./types";

class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(base: string, path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${base}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      detail = body.detail ?? body.error ?? detail;
    } catch {
      // non-JSON error body
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

const u = <T>(path: string, init?: RequestInit) =>
  request<T>("/api/backend", path, init);
const a = <T>(path: string, init?: RequestInit) =>
  request<T>("/api/admin", path, init);

export { ApiError };

// ── User-facing API ──────────────────────────────────────────────────

export const api = {
  // users
  getMe: () => u<UserProfile>("/users/me"),
  updateMe: (payload: { name?: string; phone_number?: string | null }) =>
    u<UserProfile>("/users/me", { method: "PATCH", body: JSON.stringify(payload) }),

  // alerts
  getAlerts: (page = 1, limit = 20, topicId?: string) =>
    u<Paginated<Alert>>(
      `/alerts?page=${page}&limit=${limit}${topicId ? `&topic_id=${topicId}` : ""}`,
    ),
  deleteAlert: (id: string) => u<unknown>(`/alerts/${id}`, { method: "DELETE" }),

  // topics
  getTopics: (page = 1, limit = 20) =>
    u<Paginated<Topic>>(`/topics?page=${page}&limit=${limit}`),
  getTopic: (id: string) => u<Topic>(`/topics/${id}`),
  createTopic: (payload: {
    name: string;
    description: string;
    sensitivity: string;
  }) => u<Topic>("/topics", { method: "POST", body: JSON.stringify(payload) }),
  updateTopic: (id: string, payload: Partial<Topic>) =>
    u<Topic>(`/topics/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteTopic: (id: string) => u<unknown>(`/topics/${id}`, { method: "DELETE" }),
  getChannels: (id: string) =>
    u<{ channel: DeliveryChannel }[]>(`/topics/${id}/channels`),
  updateChannels: (id: string, channels: DeliveryChannel[]) =>
    u<unknown>(`/topics/${id}/channels`, {
      method: "PUT",
      body: JSON.stringify(channels.map((channel) => ({ channel }))),
    }),

  // discovery
  triggerDiscovery: (topicId: string) =>
    u<unknown>(`/topics/${topicId}/discover`, { method: "POST" }),
  getDiscoveryStatus: (topicId: string) =>
    u<DiscoveryStatus>(`/topics/${topicId}/discovery/status`),

  // intelligence
  getTopicIntelligence: (topicId: string) =>
    u<TopicIntelligence>(`/topics/${topicId}/intelligence`),
  getHistoryTimestamps: (topicId: string) =>
    u<{ timestamps: HistoryTimestamp[] }>(
      `/topics/${topicId}/intelligence/history/timestamps`,
    ),
  getHistoryAtTime: (topicId: string, timestamp: string) =>
    u<{ sub_themes: SubTheme[] }>(
      `/topics/${topicId}/intelligence/history?timestamp=${encodeURIComponent(timestamp)}`,
    ),
  getTimeline: (topicId: string, subThemeId: string, limit = 20) =>
    u<{ sub_theme_label: string | null; snapshots: TimelineSnapshot[] }>(
      `/topics/${topicId}/intelligence/timeline?sub_theme_id=${subThemeId}&limit=${limit}`,
    ),
  getSubThemeArticles: (topicId: string, subThemeId: string, page = 1, limit = 20) =>
    u<Paginated<Alert>>(
      `/topics/${topicId}/intelligence/sub-themes/${subThemeId}/articles?page=${page}&limit=${limit}`,
    ),
  getArticleComments: (articleId: string) =>
    u<{ comments: RedditComment[] }>(`/articles/${articleId}/comments`),

  // websocket ticket
  getWsTicket: () => u<{ ticket: string }>("/ws/ticket", { method: "POST" }),
};

// ── Admin API (X-Admin-Key attached server-side) ─────────────────────

export const adminApi = {
  signIn: (key: string) =>
    request<{ ok: boolean }>("/api", "/admin-session", {
      method: "POST",
      body: JSON.stringify({ key }),
    }),
  signOut: () =>
    request<{ ok: boolean }>("/api", "/admin-session", { method: "DELETE" }),
  impersonate: (userId: string) =>
    request<{ ok: boolean }>("/api", "/impersonate", {
      method: "POST",
      body: JSON.stringify({ userId }),
    }),
  stopImpersonation: () =>
    request<{ ok: boolean }>("/api", "/impersonate", { method: "DELETE" }),

  getUsers: () => a<{ users: AdminUser[] }>("/users"),
  deleteUser: (userId: string) =>
    a<unknown>(`/users/${userId}`, { method: "DELETE" }),
  getUserTopics: (userId: string) => a<AdminTopic[]>(`/users/${userId}/topics`),
  discoverTopic: (userId: string, topicId: string) =>
    a<unknown>(`/users/${userId}/topics/${topicId}/discover`, { method: "POST" }),
  discoverAll: () => a<{ task_id?: string }>("/discover/all", { method: "POST" }),
  getTopicSubthemes: (userId: string, topicId: string) =>
    a<AdminSubTheme[]>(`/users/${userId}/topics/${topicId}/subthemes`),
  deleteTopicSubthemes: (userId: string, topicId: string) =>
    a<unknown>(`/users/${userId}/topics/${topicId}/subthemes`, { method: "DELETE" }),

  getSources: () => a<SourceStat[]>("/sources"),
  getPipeline: () => a<PipelineRow[]>("/pipeline"),
  getSubthemes: () => a<AdminSubTheme[]>("/subthemes"),
  deleteSubtheme: (id: string) => a<unknown>(`/subthemes/${id}`, { method: "DELETE" }),
  deleteSubthemes: () => a<unknown>("/subthemes", { method: "DELETE" }),
  getArticles: () => a<AdminArticles>("/articles"),
  deleteArticles: () => a<unknown>("/articles", { method: "DELETE" }),

  getIngestionSources: () => a<IngestionSource[]>("/ingestion/sources"),
  updateSource: (id: string, data: Partial<IngestionSource>) =>
    a<unknown>(`/ingestion/sources/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  getSourceFeeds: (sourceId: string) =>
    a<SourceFeed[]>(`/ingestion/sources/${sourceId}/feeds`),
  updateFeed: (feedId: string, data: Partial<SourceFeed>) =>
    a<unknown>(`/ingestion/feeds/${feedId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  getSubreddits: () => a<Subreddit[]>("/ingestion/reddit/subreddits"),
  addSubreddit: (data: { name: string; limit_per_crawl: number; sort: string }) =>
    a<unknown>("/ingestion/reddit/subreddits", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateSubreddit: (id: string, data: Partial<Subreddit>) =>
    a<unknown>(`/ingestion/reddit/subreddits/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  deleteSubreddit: (id: string) =>
    a<unknown>(`/ingestion/reddit/subreddits/${id}`, { method: "DELETE" }),

  getSettings: () => a<SystemSetting[]>("/settings"),
  updateSetting: (key: string, value: number | string) =>
    a<unknown>(`/settings/${key}`, {
      method: "PATCH",
      body: JSON.stringify({ value }),
    }),
};
