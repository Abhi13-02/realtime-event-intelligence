"use client";

// Discovery timeline card — the topic-level time-travel control. Snapshots come
// from GET /topics/{id}/intelligence/history/timestamps (one per discovery run).
// Selecting a run replays the narrative state at that moment via the history
// endpoint.
//
// The scrubbing itself lives in RunScrubber, shared with the narrative
// deep-dive chart: dragging moves the handle freely and commits once on
// release, rather than firing a fetch on every intermediate position.

import { History } from "lucide-react";
import RunScrubber from "@/components/run-scrubber";
import type { HistoryTimestamp } from "@/lib/types";
import { runStamp, timeAgoLong } from "@/lib/format";

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

  const isLatest = activeIdx === timestamps.length - 1;
  const activeTs = timestamps[activeIdx].ts;

  return (
    <div
      className="bg-panel border border-line"
      style={{ borderRadius: "var(--radius)", padding: "15px 20px 13px", marginBottom: 14, flex: "none" }}
    >
      <div className="flex items-center justify-between flex-wrap" style={{ gap: 8, marginBottom: 4 }}>
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
                style={{ fontSize: 10.5, fontWeight: 600, background: "transparent", border: "none", padding: 0, cursor: "pointer" }}
              >
                Jump to latest
              </button>
            </>
          )}
          {/* Compound relative time: discovery runs every few hours, so "3d ago"
              collapsed several distinct runs onto one indistinguishable label. */}
          <span className="text-dim font-mono" style={{ fontSize: 11 }}>
            {isLatest ? "Latest" : "Snapshot"} · {timeAgoLong(activeTs)}
          </span>
        </div>
      </div>

      <div style={{ margin: "10px 0 0" }}>
        <RunScrubber
          count={timestamps.length}
          activeIdx={activeIdx}
          onSelect={onSelect}
          labelFor={(i) => `${runStamp(timestamps[i].ts)} · ${timeAgoLong(timestamps[i].ts)}`}
        />
      </div>

      <div className="flex justify-between" style={{ margin: "4px 8px 0" }}>
        <div className="flex flex-col">
          <span className="eyebrow" style={{ fontSize: 8, marginBottom: 1 }}>
            First run
          </span>
          <span className="text-mute" style={{ fontSize: 10 }}>
            {timeAgoLong(timestamps[0].ts)}
          </span>
        </div>
        <div className="flex flex-col items-center">
          <span className="eyebrow" style={{ fontSize: 8, marginBottom: 1 }}>
            Viewing
          </span>
          <span className="text-ink font-mono" style={{ fontSize: 10 }}>
            {runStamp(activeTs)}
          </span>
        </div>
        <div className="flex flex-col items-end">
          <span className="eyebrow" style={{ fontSize: 8, marginBottom: 1, color: "var(--accent2)" }}>
            Latest run
          </span>
          <span className="text-dim" style={{ fontSize: 10 }}>
            {timeAgoLong(timestamps[timestamps.length - 1].ts)}
          </span>
        </div>
      </div>
    </div>
  );
}
