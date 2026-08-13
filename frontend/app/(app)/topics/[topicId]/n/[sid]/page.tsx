"use client";

// Narrative Timeline — the cluster drill-down (handoff screen 6) backed
// entirely by real data: snapshot series from the timeline endpoint,
// stat cards derived from those runs, and the old frontend's evidence
// feed (news/reddit toggle, per-post analyzed comments) below the chart.
// Sentiment and the Reddit half of the evidence feed are gated behind
// SOCIAL_SIGNALS_ENABLED while Reddit ingestion is offline.

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import AlertCard from "@/components/alert-card";
import RunScrubber from "@/components/run-scrubber";
import TimelineChart from "@/components/timeline-chart";
import { NewBadge, Pager, RevivalBadge, StatusChip } from "@/components/ui";
import { api } from "@/lib/api";
import type { Alert, SubTheme, TimelineSnapshot } from "@/lib/types";
import {
  SOCIAL_SIGNALS_ENABLED,
  formatVolume,
  growthColor,
  growthDisplay,
  runStamp,
  sentimentColor,
  sentimentDisplay,
  timeAgo,
  timeAgoLong,
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

  // ── time travel ───────────────────────────────────────────────────────
  // `at` is the run being viewed. null means "latest". It lives in the URL so
  // refresh, the back button and shared links all restore the same view.
  const searchParams = useSearchParams();
  const router = useRouter();
  const at = searchParams.get("at");

  // Chart data is the full history regardless of which run is selected —
  // truncating at the selection would make it impossible to scrub forward.
  useEffect(() => {
    if (!topicId || !subThemeId) return;
    api
      .getTimeline(topicId, subThemeId, 100)
      // API returns newest first — chart wants chronological
      .then((tl) => setSnapshots((tl.snapshots ?? []).slice().reverse()))
      .catch(() => setSnapshots([]));
    api
      .getTopicIntelligence(topicId)
      .then((intel) => setTopicName(intel.topic_name ?? ""))
      .catch(() => setTopicName("")); // breadcrumb only — never blocks the page
  }, [topicId, subThemeId]);

  // Header/stats re-fetch whenever the selected run changes, so the title,
  // description, volume, growth, status and representative article all shift
  // to that run together rather than mixing today's values with old numbers.
  useEffect(() => {
    if (!topicId || !subThemeId) return;
    setLoading(true);
    setError("");
    // Fetch this narrative directly. Reading it out of the topic's LIVE payload
    // meant a narrative that had gone dormant was filtered out before we ever
    // saw it, so opening one from the timeline failed even though its chart
    // data had loaded fine. This endpoint applies no status filter — a dormant
    // narrative resolves and simply reports volume 0.
    api
      .getSubTheme(topicId, subThemeId, at ?? undefined)
      .then(setTheme)
      .catch(() => setError("Failed to load narrative data."))
      .finally(() => setLoading(false));
  }, [topicId, subThemeId, at]);

  // Evidence list follows the same run.
  useEffect(() => {
    if (!topicId || !subThemeId) return;
    api
      .getSubThemeArticles(topicId, subThemeId, evPage, EV_PAGE_SIZE, at ?? undefined)
      .then((res) => {
        setArticles(res.data ?? []);
        setEvTotal(res.total_count ?? 0);
      })
      .catch(() => setArticles([]));
  }, [topicId, subThemeId, evPage, at]);

  const selectedIdx = useMemo(() => {
    if (snapshots.length === 0) return undefined;
    if (!at) return snapshots.length - 1; // no ?at= → latest
    const t = new Date(at).getTime();
    const i = snapshots.findIndex((s) => new Date(s.snapshot_at).getTime() === t);
    return i >= 0 ? i : snapshots.length - 1;
  }, [snapshots, at]);

  const selectRun = (idx: number) => {
    const snap = snapshots[idx];
    if (!snap) return;
    setEvPage(1); // a different run has a different article set
    const isLatest = idx === snapshots.length - 1;
    // replace, not push — scrubbing should not fill the back stack
    router.replace(
      isLatest
        ? `/topics/${topicId}/n/${subThemeId}`
        : `/topics/${topicId}/n/${subThemeId}?at=${encodeURIComponent(snap.snapshot_at)}`,
      { scroll: false },
    );
  };

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
    // Reaching here now means the narrative genuinely does not exist in this
    // topic — the API 404'd — rather than merely being absent from today's
    // active set.
    return (
      <div className="grid place-items-center text-mute" style={{ height: "100%", fontSize: 13 }}>
        {error || "Narrative not found."}
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
            {(theme.status === "new" || theme.is_new) && <NewBadge />}
            {(theme.status === "revival" || theme.is_revival) && <RevivalBadge />}
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
        {SOCIAL_SIGNALS_ENABLED &&
          statCard(
            "Avg sentiment",
            stats?.avgSent != null ? sentimentDisplay(stats.avgSent) : "N/A",
            "across all runs",
            stats?.avgSent != null ? sentimentColor(stats.avgSent) : undefined,
          )}
        {statCard(
          "Growth",
          growthDisplay(theme.growth_pct),
          theme.prev_volume != null
            ? `vs. ${formatVolume(theme.prev_volume)} last run`
            : "no prior run",
          growthColor(theme.status, theme.growth_pct),
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
          {SOCIAL_SIGNALS_ENABLED && (
            <div className="flex items-center" style={{ gap: 6 }}>
              <span style={{ width: 12, height: 3, borderRadius: 2, background: "var(--warn)" }} />
              <span className="text-dim" style={{ fontSize: 11, fontWeight: 500 }}>Sentiment</span>
            </div>
          )}
          <div className="flex-1" />
          <span className="text-mute" style={{ fontSize: 10.5 }}>
            one point per discovery run · drag to travel
          </span>
        </div>
        <TimelineChart
          snapshots={snapshots}
          selectedIdx={selectedIdx}
          onSelect={selectRun}
        />
        {snapshots.length > 1 && selectedIdx != null && (
          <div style={{ padding: "2px 4px 10px" }}>
            <RunScrubber
              count={snapshots.length}
              activeIdx={selectedIdx}
              onSelect={selectRun}
              labelFor={(i) => runStamp(snapshots[i].snapshot_at)}
            />
            <div
              className="flex items-center justify-between"
              style={{ gap: 10, marginTop: 6, padding: "0 8px" }}
            >
              <span className="text-mute" style={{ fontSize: 10 }}>
                {timeAgoLong(snapshots[0].snapshot_at)}
              </span>
              <div className="flex items-center" style={{ gap: 9 }}>
                {at && (
                  <>
                    <span
                      className="text-warn bg-warnsoft"
                      style={{ fontSize: 9.5, fontWeight: 600, padding: "2px 8px", borderRadius: 99, letterSpacing: ".03em" }}
                    >
                      REPLAYING
                    </span>
                    <button
                      onClick={() => selectRun(snapshots.length - 1)}
                      className="text-dim hover:text-accent2 transition-colors"
                      style={{ fontSize: 10.5, fontWeight: 600, background: "transparent", border: "none", padding: 0, cursor: "pointer" }}
                    >
                      Jump to latest
                    </button>
                  </>
                )}
                <span className="text-ink font-mono" style={{ fontSize: 10.5 }}>
                  Viewing {runStamp(snapshots[selectedIdx].snapshot_at)}
                </span>
              </div>
              <span className="text-mute" style={{ fontSize: 10 }}>
                {timeAgoLong(snapshots[snapshots.length - 1].snapshot_at)}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* evidence feed — news/reddit toggle, comments expand on reddit posts */}
      <div className="flex items-center justify-between" style={{ marginBottom: 12 }}>
        <div className="eyebrow" style={{ fontSize: 11, letterSpacing: ".05em" }}>
          Evidence feed
        </div>
        {SOCIAL_SIGNALS_ENABLED && (
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
        )}
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
