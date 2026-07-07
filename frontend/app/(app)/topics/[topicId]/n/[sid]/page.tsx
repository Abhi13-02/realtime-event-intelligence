"use client";

// Narrative Timeline — the cluster drill-down (handoff screen 6) backed
// entirely by real data: snapshot series from the timeline endpoint,
// stat cards derived from those runs, and the old frontend's evidence
// feed (news/reddit toggle, per-post analyzed comments) below the chart.

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import AlertCard from "@/components/alert-card";
import TimelineChart from "@/components/timeline-chart";
import { NewBadge, Pager, RevivalBadge, StatusChip } from "@/components/ui";
import { api } from "@/lib/api";
import type { Alert, SubTheme, TimelineSnapshot } from "@/lib/types";
import {
  formatVolume,
  growthDisplay,
  sentimentColor,
  sentimentDisplay,
  timeAgo,
} from "@/lib/format";

const EV_PAGE_SIZE = 20;

export default function NarrativeTimelinePage() {
  const { topicId, sid: subThemeId } = useParams<{ topicId: string; sid: string }>();

  const [theme, setTheme] = useState<SubTheme | null>(null);
  const [topicName, setTopicName] = useState("");
  const [snapshots, setSnapshots] = useState<TimelineSnapshot[]>([]);
  const [articles, setArticles] = useState<Alert[]>([]);
  const [evPage, setEvPage] = useState(1);
  const [evTotal, setEvTotal] = useState(0);
  const [showReddit, setShowReddit] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!topicId || !subThemeId) return;
    setLoading(true);
    setError("");
    Promise.all([
      api.getTopicIntelligence(topicId),
      api.getTimeline(topicId, subThemeId, 50),
    ])
      .then(([intel, timeline]) => {
        setTopicName(intel.topic_name ?? "");
        setTheme(intel.sub_themes.find((s) => s.id === subThemeId) ?? null);
        // API returns newest first — chart wants chronological
        setSnapshots((timeline.snapshots ?? []).slice().reverse());
      })
      .catch(() => setError("Failed to load narrative data."))
      .finally(() => setLoading(false));
  }, [topicId, subThemeId]);

  useEffect(() => {
    if (!topicId || !subThemeId) return;
    api
      .getSubThemeArticles(topicId, subThemeId, evPage, EV_PAGE_SIZE)
      .then((res) => {
        setArticles(res.data ?? []);
        setEvTotal(res.total_count ?? 0);
      })
      .catch(() => setArticles([]));
  }, [topicId, subThemeId, evPage]);

  const stats = useMemo(() => {
    if (snapshots.length === 0) return null;
    const peak = snapshots.reduce((a, b) => (b.total_volume > a.total_volume ? b : a));
    const sentVals = snapshots
      .map((s) => s.sentiment_score)
      .filter((v): v is number => v != null);
    const avgSent =
      sentVals.length > 0 ? sentVals.reduce((a, b) => a + b, 0) / sentVals.length : null;
    return { peak, avgSent };
  }, [snapshots]);

  const filtered = useMemo(
    () =>
      articles.filter((a) =>
        showReddit ? a.membership_type === "reddit" : a.membership_type !== "reddit",
      ),
    [articles, showReddit],
  );
  const evTotalPages = Math.max(1, Math.ceil(evTotal / EV_PAGE_SIZE));

  if (loading) {
    return (
      <div className="grid place-items-center text-mute" style={{ height: "100%", fontSize: 13 }}>
        Loading…
      </div>
    );
  }
  if (error || !theme) {
    return (
      <div className="grid place-items-center text-mute" style={{ height: "100%", fontSize: 13 }}>
        {error || "Narrative not found in the latest snapshot."}
      </div>
    );
  }

  const statCard = (label: string, value: React.ReactNode, sub: string, color?: string) => (
    <div className="bg-panel border border-line" style={{ borderRadius: "var(--radius)", padding: "14px 15px" }}>
      <div className="eyebrow" style={{ marginBottom: 8 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 600, lineHeight: 1, color: color ?? "var(--text)" }}>{value}</div>
      <div className="text-mute" style={{ fontSize: 10.5, marginTop: 6 }}>{sub}</div>
    </div>
  );

  return (
    <div style={{ maxWidth: 1080, margin: "0 auto", padding: "22px 24px 44px" }}>
      <div className="flex items-center" style={{ gap: 10, marginBottom: 6 }}>
        <Link
          href={`/topics/${topicId}`}
          className="flex items-center bg-bg2 border border-line2 text-dim hover:text-ink transition-colors"
          style={{ height: 26, padding: "0 10px 0 7px", borderRadius: "var(--radiussm)", gap: 5, fontSize: 11.5, fontWeight: 550 }}
        >
          <span style={{ fontSize: 14, lineHeight: 1, marginTop: -1 }}>‹</span>
          Back to deep dive
        </Link>
        {topicName && (
          <span
            style={{ fontSize: 11, fontWeight: 600, color: "var(--accent2)", background: "var(--accentsoft)", padding: "3px 9px", borderRadius: 99 }}
          >
            {topicName}
          </span>
        )}
      </div>

      <div className="flex items-start flex-wrap" style={{ gap: 12, marginBottom: 18 }}>
        <div className="min-w-0 flex-1">
          <div className="flex items-center flex-wrap" style={{ gap: 9, marginBottom: 5 }}>
            <span className="text-ink" style={{ fontSize: 19, fontWeight: 600, letterSpacing: "-.02em" }}>
              {theme.label ?? "Unlabeled cluster"}
            </span>
            <StatusChip status={theme.status} />
            {theme.is_new && <NewBadge />}
            {theme.is_revival && <RevivalBadge />}
          </div>
          {theme.description && (
            <div className="text-mute" style={{ fontSize: 12.5, lineHeight: 1.5, maxWidth: 640 }}>
              {theme.description}
            </div>
          )}
        </div>
      </div>

      {/* stat cards — real values from the snapshot series */}
      <div
        className="grid"
        style={{ gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))", gap: "var(--gap)", marginBottom: 16 }}
      >
        {statCard(
          "Peak volume",
          stats ? formatVolume(stats.peak.total_volume) : "—",
          stats ? `mentions · ${timeAgo(stats.peak.snapshot_at)}` : "no runs yet",
        )}
        {statCard("Current volume", formatVolume(theme.total_volume), "mentions tracked")}
        {statCard(
          "Avg sentiment",
          stats?.avgSent != null ? sentimentDisplay(stats.avgSent) : "N/A",
          "across all runs",
          stats?.avgSent != null ? sentimentColor(stats.avgSent) : undefined,
        )}
        {statCard(
          "Growth",
          theme.is_new ? "NEW" : growthDisplay(theme.growth_pct),
          "vs. prior window",
          theme.is_new
            ? "var(--accent2)"
            : (theme.growth_pct ?? 0) >= 0
              ? "var(--pos)"
              : "var(--warn)",
        )}
        {statCard("Discovery runs", String(snapshots.length), "snapshots recorded")}
      </div>

      {/* chart card */}
      <div
        className="bg-panel border border-line"
        style={{ borderRadius: "var(--radius)", padding: "18px 18px 8px", marginBottom: 18 }}
      >
        <div className="flex items-center" style={{ gap: 18, marginBottom: 6, padding: "0 4px" }}>
          <div className="flex items-center" style={{ gap: 6 }}>
            <span style={{ width: 12, height: 3, borderRadius: 2, background: "var(--accent)" }} />
            <span className="text-dim" style={{ fontSize: 11, fontWeight: 500 }}>Volume</span>
          </div>
          <div className="flex items-center" style={{ gap: 6 }}>
            <span style={{ width: 12, height: 3, borderRadius: 2, background: "var(--warn)" }} />
            <span className="text-dim" style={{ fontSize: 11, fontWeight: 500 }}>Sentiment</span>
          </div>
          <div className="flex-1" />
          <span className="text-mute" style={{ fontSize: 10.5 }}>
            one point per discovery run · hover for values
          </span>
        </div>
        <TimelineChart snapshots={snapshots} />
      </div>

      {/* evidence feed — news/reddit toggle, comments expand on reddit posts */}
      <div className="flex items-center justify-between" style={{ marginBottom: 12 }}>
        <div className="eyebrow" style={{ fontSize: 11, letterSpacing: ".05em" }}>
          Evidence feed
        </div>
        <div
          className="flex bg-bg2 border border-line"
          style={{ gap: 4, borderRadius: "var(--radius)", padding: 3 }}
        >
          {(
            [
              [false, "News"],
              [true, "Reddit"],
            ] as const
          ).map(([val, label]) => (
            <button
              key={label}
              onClick={() => setShowReddit(val)}
              className="transition-colors"
              style={{
                padding: "5px 14px",
                borderRadius: "var(--radiussm)",
                fontSize: 11.5,
                fontWeight: 600,
                border: "none",
                background: showReddit === val ? "var(--accent)" : "transparent",
                color: showReddit === val ? "var(--accentfg)" : "var(--textmute)",
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {filtered.length === 0 ? (
        <div
          className="text-center text-mute border border-dashed border-line"
          style={{ padding: "40px 12px", borderRadius: "var(--radius)", fontSize: 12.5 }}
        >
          No {showReddit ? "Reddit posts" : "news articles"} found for this cluster.
        </div>
      ) : (
        <div className="flex flex-col" style={{ gap: "var(--gap)" }}>
          {filtered.map((article) => (
            <AlertCard key={article.id} alert={article} hideTopicTag />
          ))}
        </div>
      )}
      {evTotalPages > 1 && (
        <Pager
          page={evPage}
          totalPages={evTotalPages}
          onPrev={() => setEvPage((p) => Math.max(1, p - 1))}
          onNext={() => setEvPage((p) => Math.min(evTotalPages, p + 1))}
        />
      )}
    </div>
  );
}
