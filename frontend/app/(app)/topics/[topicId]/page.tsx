"use client";

// Topic Deep Dive — hero screen. Fits the viewport (no page scroll): fixed
// header row, then Live Datastream (40%) + Discovery timeline / Narrative
// clusters (60%), each column scrolling internally with a pinned pager.
// All data real: alerts stream (+ WebSocket inject), sub-theme clusters,
// Run Discovery driving the actual Celery task with polled stage progress,
// and the time-travel scrubber replaying any past discovery run.

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ChevronDown, Radar, Check } from "lucide-react";
import NarrativeCard from "@/components/narrative-card";
import TimeTravel from "@/components/time-travel";
import AlertCard from "@/components/alert-card";
import { Pager } from "@/components/ui";
import { api } from "@/lib/api";
import { useWebSocket } from "@/lib/websocket";
import type { Alert, HistoryTimestamp, SubTheme, Topic } from "@/lib/types";

const DS_PAGE_SIZE = 20;

export default function DeepDivePage() {
  const { topicId } = useParams<{ topicId: string }>();
  const router = useRouter();
  const { latestAlert } = useWebSocket();

  // topic header
  const [topicName, setTopicName] = useState("Loading…");
  const [topicDescription, setTopicDescription] = useState("");
  const [sensitivity, setSensitivity] = useState("");
  const [editingSens, setEditingSens] = useState(false);
  const [allTopics, setAllTopics] = useState<Topic[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);

  // datastream
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [dsPage, setDsPage] = useState(1);
  const [dsTotalPages, setDsTotalPages] = useState(1);

  // clusters + history
  const [subThemes, setSubThemes] = useState<SubTheme[]>([]);
  const [loading, setLoading] = useState(true);
  const [historyTs, setHistoryTs] = useState<HistoryTimestamp[]>([]);
  const [historyIdx, setHistoryIdx] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);

  // discovery
  const [discovering, setDiscovering] = useState(false);
  const [discPct, setDiscPct] = useState(0);
  const [discStage, setDiscStage] = useState("");
  const [discMsg, setDiscMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const discoveringRef = useRef(false);

  // responsive tabs (<880px per handoff)
  const [narrow, setNarrow] = useState(false);
  const [mobileTab, setMobileTab] = useState<"stream" | "clusters">("clusters");

  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < 880);
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // ── data loading ────────────────────────────────────────────────

  const loadIntelligence = useCallback(async () => {
    const intel = await api.getTopicIntelligence(topicId);
    setSubThemes(intel.sub_themes ?? []);
    setTopicName(intel.topic_name ?? "Unknown topic");
    setTopicDescription(intel.topic_description ?? "");
    setSensitivity(intel.sensitivity ?? "");
  }, [topicId]);

  const loadHistory = useCallback(async () => {
    const data = await api.getHistoryTimestamps(topicId);
    // API returns newest first; keep oldest → newest for the scrubber
    const sorted = (data.timestamps ?? []).slice().reverse();
    setHistoryTs(sorted);
    setHistoryIdx(Math.max(0, sorted.length - 1));
  }, [topicId]);

  useEffect(() => {
    if (!topicId) return;
    setLoading(true);
    Promise.allSettled([loadIntelligence(), loadHistory()]).finally(() =>
      setLoading(false),
    );
    api
      .getTopics(1, 50)
      .then((res) => setAllTopics(res.data ?? []))
      .catch(() => {});
  }, [topicId, loadIntelligence, loadHistory]);

  useEffect(() => {
    if (!topicId) return;
    api
      .getAlerts(dsPage, DS_PAGE_SIZE, topicId)
      .then((res) => {
        setAlerts(res.data ?? []);
        setDsTotalPages(Math.max(1, Math.ceil((res.total_count ?? 0) / DS_PAGE_SIZE)));
      })
      .catch(() => setAlerts([]));
  }, [topicId, dsPage]);

  // live inject on page 1, matching topic only
  useEffect(() => {
    if (latestAlert && latestAlert.topic_id === topicId && dsPage === 1) {
      setAlerts((prev) =>
        prev.some((a) => a.id === latestAlert.id) ? prev : [latestAlert, ...prev],
      );
    }
  }, [latestAlert, topicId, dsPage]);

  // ── time travel ─────────────────────────────────────────────────

  const selectSnapshot = async (idx: number) => {
    setHistoryIdx(idx);
    setHistoryLoading(true);
    try {
      if (idx === historyTs.length - 1) {
        await loadIntelligence(); // latest = live state
      } else {
        const hist = await api.getHistoryAtTime(topicId, historyTs[idx].ts);
        setSubThemes(hist.sub_themes ?? []);
      }
    } catch {
      // keep current view on failure
    } finally {
      setHistoryLoading(false);
    }
  };

  // ── discovery (poll the real Celery task) ───────────────────────

  const runDiscovery = async () => {
    if (discovering) return;
    setDiscovering(true);
    discoveringRef.current = true;
    setDiscPct(0);
    setDiscStage("Queued");
    setDiscMsg(null);
    try {
      await api.triggerDiscovery(topicId);
    } catch (err) {
      setDiscovering(false);
      discoveringRef.current = false;
      setDiscMsg({
        type: "err",
        text: err instanceof Error ? err.message : "Discovery failed to start.",
      });
      setTimeout(() => setDiscMsg(null), 5000);
    }
  };

  useEffect(() => {
    if (!topicId) return;
    let mounted = true;

    const check = async () => {
      try {
        const { status, progress, message } = await api.getDiscoveryStatus(topicId);
        if (!mounted) return;
        if (["PROGRESS", "STARTED", "PENDING", "processing"].includes(status)) {
          discoveringRef.current = true;
          setDiscovering(true);
          setDiscPct(progress ?? 0);
          setDiscStage(message ?? "Discovering…");
        } else if (status === "SUCCESS" && discoveringRef.current) {
          discoveringRef.current = false;
          setDiscovering(false);
          setDiscPct(100);
          setDiscMsg({
            type: message?.toLowerCase().includes("skipped") ? "err" : "ok",
            text: message ?? "Narrative clusters updated.",
          });
          await Promise.allSettled([loadIntelligence(), loadHistory()]);
          setTimeout(() => setDiscMsg(null), 5000);
        } else if (status === "FAILURE" && discoveringRef.current) {
          discoveringRef.current = false;
          setDiscovering(false);
          setDiscPct(0);
          setDiscMsg({ type: "err", text: "Discovery task failed." });
          setTimeout(() => setDiscMsg(null), 5000);
        }
      } catch {
        // transient poll failure — keep going
      }
    };

    check();
    const interval = setInterval(check, 2000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [topicId, loadIntelligence, loadHistory]);

  // ── sensitivity inline edit ─────────────────────────────────────

  const updateSensitivity = async (level: string) => {
    if (level === sensitivity) {
      setEditingSens(false);
      return;
    }
    try {
      await api.updateTopic(topicId, { sensitivity: level as Topic["sensitivity"] });
      setSensitivity(level);
    } finally {
      setEditingSens(false);
    }
  };

  const showStream = !narrow || mobileTab === "stream";
  const showClusters = !narrow || mobileTab === "clusters";

  return (
    <div
      className="flex flex-col"
      style={{ height: "100%", padding: "16px 24px", overflow: "hidden" }}
    >
      {/* header row */}
      <div
        className="flex items-center flex-wrap"
        style={{ gap: 12, marginBottom: 14, flex: "none" }}
      >
        <div style={{ position: "relative" }}>
          <button
            onClick={() => setPickerOpen(!pickerOpen)}
            className="flex items-center bg-panel border border-line hover:border-line2 text-ink transition-colors"
            style={{ gap: 7, height: 32, padding: "0 10px", borderRadius: "var(--radius)" }}
          >
            <span style={{ fontSize: 14.5, fontWeight: 600, letterSpacing: "-.01em" }}>
              {topicName}
            </span>
            <ChevronDown size={14} strokeWidth={1.55} className="text-mute" />
          </button>
          {pickerOpen && (
            <div
              style={{
                position: "absolute",
                top: 37,
                left: 0,
                zIndex: 35,
                width: 270,
                background: "var(--panel)",
                border: "1px solid var(--border2)",
                borderRadius: "var(--radiuslg)",
                boxShadow: "var(--shadowlg)",
                padding: 6,
                maxHeight: 340,
                overflow: "auto",
              }}
            >
              {allTopics.map((t) => {
                const active = t.id === topicId;
                return (
                  <div
                    key={t.id}
                    onClick={() => {
                      setPickerOpen(false);
                      if (!active) router.push(`/topics/${t.id}`);
                    }}
                    className="flex items-center cursor-pointer hover:bg-bg2 transition-colors"
                    style={{ gap: 8, padding: "8px 9px", borderRadius: "var(--radiussm)" }}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="text-ink truncate" style={{ fontSize: 12.5, fontWeight: 550 }}>
                        {t.name}
                      </div>
                      <div className="text-mute truncate" style={{ fontSize: 10.5, textTransform: "capitalize" }}>
                        {t.sensitivity}
                      </div>
                    </div>
                    {active && <Check size={13} className="text-accent2" style={{ flex: "none" }} />}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {editingSens ? (
          <div className="flex items-center nifade" style={{ gap: 6 }}>
            {["broad", "balanced", "high"].map((level) => (
              <button
                key={level}
                onClick={() => updateSensitivity(level)}
                className="transition-colors"
                style={{
                  fontSize: 10.5,
                  fontWeight: 600,
                  padding: "3px 10px",
                  borderRadius: 99,
                  textTransform: "capitalize",
                  border: `1px solid ${sensitivity === level ? "var(--accent)" : "var(--border2)"}`,
                  background: sensitivity === level ? "var(--accentsoft)" : "var(--bg2)",
                  color: sensitivity === level ? "var(--accent2)" : "var(--textmute)",
                }}
              >
                {level}
              </button>
            ))}
            <button
              onClick={() => setEditingSens(false)}
              className="text-mute hover:text-ink"
              style={{ fontSize: 10.5, background: "transparent", border: "none" }}
            >
              cancel
            </button>
          </div>
        ) : (
          <button
            onClick={() => setEditingSens(true)}
            title="Edit sensitivity"
            className="text-mute hover:text-dim transition-colors"
            style={{ fontSize: 11.5, background: "transparent", border: "none", padding: 0 }}
          >
            Sensitivity:{" "}
            <span className="text-dim" style={{ fontWeight: 550, textTransform: "capitalize" }}>
              {sensitivity || "—"}
            </span>{" "}
            ✎
          </button>
        )}

        <span className="text-mute" style={{ fontSize: 11.5 }}>
          ·
        </span>
        <span className="text-mute" style={{ fontSize: 11.5 }}>
          <span className="text-dim" style={{ fontWeight: 550 }}>
            {subThemes.length}
          </span>{" "}
          active narratives
        </span>
        {topicDescription && (
          <span className="text-mute truncate" style={{ fontSize: 11.5, maxWidth: 380 }}>
            · {topicDescription}
          </span>
        )}
      </div>

      {/* mobile tab switcher */}
      {narrow && (
        <div
          className="flex bg-bg2 border border-line"
          style={{ gap: 4, borderRadius: "var(--radius)", padding: 3, marginBottom: 14, maxWidth: 400, flex: "none" }}
        >
          {(
            [
              ["stream", "Live Datastream"],
              ["clusters", "Narrative Clusters"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setMobileTab(key)}
              className="flex-1 transition-colors"
              style={{
                padding: "6px 0",
                borderRadius: "var(--radiussm)",
                fontSize: 11.5,
                fontWeight: 600,
                border: "none",
                background: mobileTab === key ? "var(--accent)" : "transparent",
                color: mobileTab === key ? "var(--accentfg)" : "var(--textmute)",
              }}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      {loading ? (
        <div className="flex-1 grid place-items-center text-mute" style={{ fontSize: 13 }}>
          Loading…
        </div>
      ) : (
        <div
          className="flex-1"
          style={{
            display: "grid",
            gridTemplateColumns: narrow ? "1fr" : "2fr 3fr",
            gap: 20,
            minHeight: 0,
            overflow: "hidden",
          }}
        >
          {/* LEFT — live datastream */}
          {showStream && (
            <section className="flex flex-col" style={{ minWidth: 0, minHeight: 0, height: "100%" }}>
              <div className="flex items-center" style={{ gap: 8, marginBottom: 12, flex: "none" }}>
                <div className="nipulse" style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--pos)" }} />
                <span className="text-ink" style={{ fontSize: 12, fontWeight: 600 }}>
                  Live datastream
                </span>
                <span className="text-mute" style={{ fontSize: 10.5 }}>
                  · newest first
                </span>
              </div>
              <div
                className="flex-1 flex flex-col"
                style={{ minHeight: 0, overflow: "auto", gap: 9, paddingRight: 3 }}
              >
                {alerts.length === 0 ? (
                  <div
                    className="text-center text-mute border border-dashed border-line"
                    style={{ padding: "48px 12px", borderRadius: "var(--radius)", fontSize: 12.5 }}
                  >
                    No active alerts matching this topic.
                  </div>
                ) : (
                  alerts.map((alert) => (
                    <AlertCard
                      key={alert.id}
                      alert={alert}
                      hideTopicTag
                      onDismiss={async (id) => {
                        setAlerts((prev) => prev.filter((a) => a.id !== id));
                        try {
                          await api.deleteAlert(id);
                        } catch {
                          // optimistic
                        }
                      }}
                    />
                  ))
                )}
              </div>
              {dsTotalPages > 1 && (
                <Pager
                  compact
                  page={dsPage}
                  totalPages={dsTotalPages}
                  onPrev={() => setDsPage((p) => Math.max(1, p - 1))}
                  onNext={() => setDsPage((p) => Math.min(dsTotalPages, p + 1))}
                />
              )}
            </section>
          )}

          {/* RIGHT — timeline + clusters */}
          {showClusters && (
            <div className="flex flex-col" style={{ minWidth: 0, minHeight: 0, height: "100%" }}>
              <TimeTravel
                timestamps={historyTs}
                activeIdx={historyIdx}
                onSelect={selectSnapshot}
              />

              <section className="flex flex-col" style={{ minWidth: 0, minHeight: 0, flex: 1 }}>
                <div
                  className="flex items-center justify-between"
                  style={{ gap: 10, marginBottom: 12, flex: "none" }}
                >
                  <div className="flex items-center" style={{ gap: 8 }}>
                    <Radar size={15} strokeWidth={1.55} className="text-mute" />
                    <span className="text-ink" style={{ fontSize: 12, fontWeight: 600 }}>
                      Narrative clusters
                    </span>
                  </div>
                  {discovering ? (
                    <div style={{ width: 220 }}>
                      <div className="flex justify-between" style={{ marginBottom: 4 }}>
                        <span className="text-dim truncate" style={{ fontSize: 10, fontWeight: 550, maxWidth: 170 }}>
                          {discStage || "Discovering…"}
                        </span>
                        <span className="font-mono" style={{ fontSize: 10, color: "var(--accent2)" }}>
                          {discPct}%
                        </span>
                      </div>
                      <div style={{ height: 4, borderRadius: 99, background: "var(--panel2)", overflow: "hidden" }}>
                        <div
                          style={{
                            height: "100%",
                            width: `${discPct}%`,
                            background: "var(--accent)",
                            borderRadius: 99,
                            transition: "width .3s",
                          }}
                        />
                      </div>
                    </div>
                  ) : (
                    <button
                      onClick={runDiscovery}
                      className="flex items-center bg-accent text-accentfg hover:bg-accent2 transition-colors"
                      style={{ height: 29, padding: "0 12px", borderRadius: "var(--radius)", border: "none", fontSize: 12, fontWeight: 600, gap: 6 }}
                    >
                      <span style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--accentfg)" }} />
                      Run discovery
                    </button>
                  )}
                </div>

                {discMsg && (
                  <div style={{ marginBottom: 10, flex: "none" }}>
                    <div
                      style={{
                        padding: "6px 12px",
                        borderRadius: "var(--radius)",
                        fontSize: 11.5,
                        fontWeight: 550,
                        color: discMsg.type === "ok" ? "var(--pos)" : "var(--neg)",
                        background: discMsg.type === "ok" ? "var(--possoft)" : "var(--negsoft)",
                      }}
                    >
                      {discMsg.type === "ok" ? "✓ " : "✕ "}
                      {discMsg.text}
                    </div>
                  </div>
                )}

                <div
                  className="flex-1"
                  style={{
                    minHeight: 0,
                    overflow: "auto",
                    display: "grid",
                    gridTemplateColumns: "repeat(2,1fr)",
                    gap: "var(--gap)",
                    alignContent: "start",
                    paddingRight: 3,
                  }}
                >
                  {historyLoading ? (
                    <div
                      className="text-center text-mute nipulse"
                      style={{ gridColumn: "1/-1", padding: "60px 0", fontSize: 12 }}
                    >
                      Reconstructing historical state…
                    </div>
                  ) : subThemes.length === 0 ? (
                    <div
                      className="text-center text-mute border border-dashed border-line"
                      style={{ gridColumn: "1/-1", padding: "48px 12px", borderRadius: "var(--radius)", fontSize: 12.5 }}
                    >
                      Insufficient data for narrative clustering.
                    </div>
                  ) : (
                    subThemes.map((theme) => (
                      <NarrativeCard
                        key={theme.id}
                        theme={theme}
                        onOpen={() =>
                          router.push(`/topics/${topicId}/n/${theme.id}`)
                        }
                      />
                    ))
                  )}
                </div>
              </section>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
