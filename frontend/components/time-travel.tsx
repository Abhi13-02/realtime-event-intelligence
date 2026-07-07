"use client";

// Discovery timeline card — the real time-travel scrubber. Snapshots come
// from GET /topics/{id}/intelligence/history/timestamps (one per discovery
// run, unbounded count). Dots are positioned proportionally to actual time,
// brighter when that run captured images. Selecting a snapshot replays the
// narrative state at that moment via the history endpoint.

import { History } from "lucide-react";
import type { HistoryTimestamp } from "@/lib/types";
import { timeAgo } from "@/lib/format";

export default function TimeTravel({
  timestamps,
  activeIdx,
  onSelect,
}: {
  timestamps: HistoryTimestamp[]; // chronological, oldest first
  activeIdx: number;
  onSelect: (idx: number) => void;
}) {
  if (timestamps.length === 0) return null;

  const start = new Date(timestamps[0].ts).getTime();
  const end = new Date(timestamps[timestamps.length - 1].ts).getTime();
  const range = Math.max(end - start, 1);
  const pct = (ts: string) =>
    range > 0 ? ((new Date(ts).getTime() - start) / range) * 100 : 100;

  const isLatest = activeIdx === timestamps.length - 1;
  const activePct = pct(timestamps[activeIdx].ts);

  const scrub = (value: number) => {
    // snap the continuous drag position to the nearest snapshot
    let best = 0;
    let bestDiff = Infinity;
    timestamps.forEach((item, i) => {
      const diff = Math.abs(new Date(item.ts).getTime() - value);
      if (diff < bestDiff) {
        bestDiff = diff;
        best = i;
      }
    });
    if (best !== activeIdx) onSelect(best);
  };

  return (
    <div
      className="bg-panel border border-line"
      style={{ borderRadius: "var(--radius)", padding: "15px 20px 13px", marginBottom: 14, flex: "none" }}
    >
      <div className="flex items-center justify-between" style={{ marginBottom: 4 }}>
        <div className="flex items-center" style={{ gap: 9 }}>
          <span className="grid place-items-center text-mute">
            <History size={15} strokeWidth={1.55} />
          </span>
          <span className="text-ink" style={{ fontSize: 12, fontWeight: 600 }}>
            Discovery timeline
          </span>
          <span className="text-mute" style={{ fontSize: 10.5 }}>
            · {timestamps.length} runs
          </span>
        </div>
        <div className="flex items-center" style={{ gap: 10 }}>
          {!isLatest && (
            <>
              <span
                className="text-warn bg-warnsoft"
                style={{ fontSize: 10, fontWeight: 600, padding: "2px 8px", borderRadius: 99, letterSpacing: ".03em" }}
              >
                REPLAYING
              </span>
              <button
                onClick={() => onSelect(timestamps.length - 1)}
                className="text-dim hover:text-accent2 transition-colors"
                style={{ fontSize: 10.5, fontWeight: 600, background: "transparent", border: "none", padding: 0 }}
              >
                Jump to latest
              </button>
            </>
          )}
          <span className="text-dim font-mono" style={{ fontSize: 11 }}>
            {isLatest ? "Latest" : "Snapshot"} · {timeAgo(timestamps[activeIdx].ts)}
          </span>
        </div>
      </div>

      <div style={{ position: "relative", height: 34, margin: "8px 6px 0" }}>
        {/* track */}
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: "50%",
            transform: "translateY(-50%)",
            height: 3,
            borderRadius: 99,
            background: "var(--border2)",
          }}
        />
        {/* filled portion up to the selected node */}
        <div
          style={{
            position: "absolute",
            left: 0,
            width: `${activePct}%`,
            top: "50%",
            transform: "translateY(-50%)",
            height: 3,
            borderRadius: 99,
            background: "var(--accent)",
            transition: "width .2s",
          }}
        />
        {/* snapshot nodes, time-proportional */}
        {timestamps.map((item, idx) => {
          const active = idx === activeIdx;
          return (
            <div
              key={item.ts}
              onClick={() => onSelect(idx)}
              title={timeAgo(item.ts)}
              style={{
                position: "absolute",
                left: `${pct(item.ts)}%`,
                top: "50%",
                transform: "translate(-50%,-50%)",
                padding: 6,
                cursor: "pointer",
                zIndex: active ? 3 : 2,
              }}
            >
              <div
                style={{
                  width: active ? 11 : item.has_images ? 7 : 5,
                  height: active ? 11 : item.has_images ? 7 : 5,
                  borderRadius: "50%",
                  background: active
                    ? "var(--accent)"
                    : item.has_images
                      ? "var(--textdim)"
                      : "var(--textmute)",
                  boxShadow: active ? "0 0 0 4px var(--accentsoft)" : "none",
                  transition: "all .2s",
                }}
              />
            </div>
          );
        })}
        {/* invisible drag overlay — continuous time, snaps to nearest run */}
        <input
          type="range"
          min={start}
          max={end}
          value={new Date(timestamps[activeIdx].ts).getTime()}
          onChange={(e) => scrub(Number(e.target.value))}
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: "50%",
            transform: "translateY(-50%)",
            width: "100%",
            margin: 0,
            opacity: 0,
            height: 24,
            cursor: "grab",
          }}
        />
      </div>

      <div className="flex justify-between" style={{ margin: "6px 6px 0" }}>
        <div className="flex flex-col">
          <span className="eyebrow" style={{ fontSize: 8, marginBottom: 1 }}>
            First run
          </span>
          <span className="text-mute" style={{ fontSize: 10 }}>
            {timeAgo(timestamps[0].ts)}
          </span>
        </div>
        <div className="flex flex-col items-end">
          <span className="eyebrow" style={{ fontSize: 8, marginBottom: 1, color: "var(--accent2)" }}>
            Latest run
          </span>
          <span className="text-dim" style={{ fontSize: 10 }}>
            {timeAgo(timestamps[timestamps.length - 1].ts)}
          </span>
        </div>
      </div>
    </div>
  );
}
