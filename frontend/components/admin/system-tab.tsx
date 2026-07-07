"use client";

// Admin › System — parity with the old panel: editable system parameters
// (thresholds + sub-theme knobs, EOM/LEAF select), global discovery
// trigger, pipeline stats, and per-source article stats.

import { useState } from "react";
import { Btn, Flash } from "@/components/ui";
import { adminApi } from "@/lib/api";
import type { PipelineRow, SourceStat, SystemSetting } from "@/lib/types";

type FlashMsg = { text: string; type: "ok" | "err" } | null;

const SETTING_ORDER: Record<string, number> = {
  threshold_broad: 1,
  threshold_balanced: 2,
  threshold_high: 3,
  subtheme_discovery_interval_hours: 4,
  subtheme_window_days: 5,
  subtheme_min_cluster_size: 6,
  subtheme_min_samples: 7,
  subtheme_cluster_selection_method: 8,
  subtheme_reddit_assign_threshold: 9,
};

function settingLabel(key: string): string {
  return key
    .replace("threshold_", "threshold · ")
    .replace(/^subtheme_/, "ST · ")
    .replace(/_/g, " ");
}

export default function SystemTab() {
  const [settings, setSettings] = useState<SystemSetting[] | null>(null);
  const [loadingSet, setLoadingSet] = useState(false);
  const [pipeline, setPipeline] = useState<PipelineRow[] | null>(null);
  const [loadingP, setLoadingP] = useState(false);
  const [sources, setSources] = useState<SourceStat[] | null>(null);
  const [loadingS, setLoadingS] = useState(false);
  const [discAll, setDiscAll] = useState(false);
  const [msg, setMsg] = useState<FlashMsg>(null);

  const flash = (text: string, type: "ok" | "err" = "ok") => {
    setMsg({ text, type });
    setTimeout(() => setMsg(null), 4000);
  };

  const loadSettings = async () => {
    setLoadingSet(true);
    try {
      setSettings(await adminApi.getSettings());
    } catch {
      flash("Failed to load settings", "err");
    } finally {
      setLoadingSet(false);
    }
  };

  const updateSetting = async (key: string, raw: string) => {
    try {
      const value =
        key === "subtheme_cluster_selection_method" ? raw : parseFloat(raw);
      await adminApi.updateSetting(key, value);
      flash(`Setting ${key} updated.`);
    } catch {
      flash("Update failed", "err");
    }
  };

  const loadPipeline = async () => {
    setLoadingP(true);
    try {
      setPipeline(await adminApi.getPipeline());
    } catch {
      flash("Failed to load pipeline", "err");
    } finally {
      setLoadingP(false);
    }
  };

  const loadSources = async () => {
    setLoadingS(true);
    try {
      setSources(await adminApi.getSources());
    } catch {
      flash("Failed to load sources", "err");
    } finally {
      setLoadingS(false);
    }
  };

  const triggerAll = async () => {
    setDiscAll(true);
    try {
      const d = await adminApi.discoverAll();
      flash(`Global discovery queued${d.task_id ? ` — task ${d.task_id.slice(0, 8)}…` : ""}`);
    } catch {
      flash("Failed", "err");
    } finally {
      setDiscAll(false);
    }
  };

  return (
    <div className="flex flex-col" style={{ gap: 20 }}>
      <Flash msg={msg} />

      {/* system parameters */}
      <div>
        <div className="flex items-center justify-between" style={{ marginBottom: 10 }}>
          <span className="eyebrow" style={{ fontSize: 11 }}>System parameters</span>
          <Btn onClick={loadSettings} disabled={loadingSet}>
            {loadingSet ? "Loading…" : "Load settings"}
          </Btn>
        </div>
        {!settings ? (
          <div
            className="text-center text-mute bg-panel border border-line"
            style={{ padding: "28px 12px", borderRadius: "var(--radius)", fontSize: 12 }}
          >
            Load settings to view and edit system thresholds.
          </div>
        ) : (
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(240px,1fr))", gap: "var(--gap)" }}>
            {[...settings]
              .sort((x, y) => (SETTING_ORDER[x.key] ?? 99) - (SETTING_ORDER[y.key] ?? 99))
              .map((s) => (
                <div key={s.key} className="bg-panel border border-line" style={{ borderRadius: "var(--radius)", padding: 14 }}>
                  <div className="eyebrow" style={{ marginBottom: 7 }}>{settingLabel(s.key)}</div>
                  {s.key === "subtheme_cluster_selection_method" ? (
                    <select
                      defaultValue={String(s.value)}
                      onChange={(e) => updateSetting(s.key, e.target.value)}
                      className="w-full bg-bg2 border border-line2 outline-none focus:border-accent font-mono"
                      style={{ padding: "7px 9px", borderRadius: "var(--radiussm)", fontSize: 12.5, color: "var(--accent2)" }}
                    >
                      <option value="eom">EOM (stable)</option>
                      <option value="leaf">LEAF (granular)</option>
                    </select>
                  ) : (
                    <input
                      type="number"
                      step={s.key.includes("threshold") ? "0.01" : "1"}
                      defaultValue={String(s.value)}
                      onBlur={(e) => updateSetting(s.key, e.target.value)}
                      className="w-full bg-bg2 border border-line2 outline-none focus:border-accent font-mono"
                      style={{ padding: "7px 9px", borderRadius: "var(--radiussm)", fontSize: 12.5, color: "var(--accent2)" }}
                    />
                  )}
                  {s.description && (
                    <div className="text-mute" style={{ fontSize: 10, marginTop: 8, lineHeight: 1.4 }}>
                      {s.description}
                    </div>
                  )}
                </div>
              ))}
          </div>
        )}
      </div>

      {/* run-all card */}
      <div className="bg-panel border border-line" style={{ borderRadius: "var(--radius)", padding: 18 }}>
        <div className="text-ink" style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 4 }}>
          Global discovery
        </div>
        <div className="text-mute" style={{ fontSize: 11.5, marginBottom: 14 }}>
          Trigger sub-theme discovery for all topics across all users.
        </div>
        <Btn variant="primary" onClick={triggerAll} disabled={discAll}>
          {discAll ? "Queuing…" : "⚡ Run discovery for all topics"}
        </Btn>
      </div>

      {/* pipeline stats */}
      <div>
        <div className="flex items-center justify-between" style={{ marginBottom: 10 }}>
          <span className="eyebrow" style={{ fontSize: 11 }}>Pipeline stats</span>
          <Btn onClick={loadPipeline} disabled={loadingP}>
            {loadingP ? "Loading…" : "Refresh"}
          </Btn>
        </div>
        {!pipeline ? (
          <div
            className="text-center text-mute bg-panel border border-line"
            style={{ padding: "28px 12px", borderRadius: "var(--radius)", fontSize: 12 }}
          >
            Refresh to load pipeline data.
          </div>
        ) : (
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(160px,1fr))", gap: "var(--gap)" }}>
            {pipeline.map((row) => (
              <div
                key={row.status ?? "null"}
                className="bg-panel border border-line text-center"
                style={{ borderRadius: "var(--radius)", padding: "15px 16px" }}
              >
                <div className="eyebrow" style={{ marginBottom: 8 }}>{row.status ?? "null"}</div>
                <div className="text-ink" style={{ fontSize: 22, fontWeight: 600, lineHeight: 1 }}>
                  {row.total}
                </div>
                <div className="text-mute" style={{ fontSize: 10.5, marginTop: 6 }}>
                  {row.has_summary} with summary
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* source stats */}
      <div>
        <div className="flex items-center justify-between" style={{ marginBottom: 10 }}>
          <span className="eyebrow" style={{ fontSize: 11 }}>Source stats</span>
          <Btn onClick={loadSources} disabled={loadingS}>
            {loadingS ? "Loading…" : "Refresh"}
          </Btn>
        </div>
        {!sources ? (
          <div
            className="text-center text-mute bg-panel border border-line"
            style={{ padding: "28px 12px", borderRadius: "var(--radius)", fontSize: 12 }}
          >
            Refresh to load source data.
          </div>
        ) : (
          <div className="bg-panel border border-line" style={{ borderRadius: "var(--radius)", overflow: "hidden" }}>
            <div
              className="grid border-b border-line eyebrow"
              style={{ gridTemplateColumns: "1.6fr .7fr .5fr .5fr .5fr", gap: 8, padding: "9px 16px" }}
            >
              <span>Source</span>
              <span>Type</span>
              <span style={{ textAlign: "right" }}>Total</span>
              <span style={{ textAlign: "right" }}>24h</span>
              <span style={{ textAlign: "right" }}>1h</span>
            </div>
            {sources.map((s, i) => (
              <div
                key={i}
                className="grid border-b border-line last:border-0 hover:bg-bg2 transition-colors"
                style={{ gridTemplateColumns: "1.6fr .7fr .5fr .5fr .5fr", gap: 8, padding: "10px 16px", alignItems: "center" }}
              >
                <span className="text-ink" style={{ fontSize: 12 }}>{s.source}</span>
                <span className="text-mute" style={{ fontSize: 11 }}>{s.type}</span>
                <span style={{ fontSize: 12, textAlign: "right", color: "var(--accent2)", fontWeight: 600 }}>{s.total}</span>
                <span className="text-dim" style={{ fontSize: 12, textAlign: "right" }}>{s.last_24h}</span>
                <span className="text-mute" style={{ fontSize: 12, textAlign: "right" }}>{s.last_1h}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
