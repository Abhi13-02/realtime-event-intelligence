"use client";

// Hand-built SVG dual-series chart per handoff (no chart library):
// volume as accent area+line on the main scale, sentiment as a warn line
// plotted bipolar (−100..+100) around a dashed zero line in the mid-band.
// Hover: vertical crosshair, dots on both series, floating tooltip.
// X points are real discovery-run snapshots.

import { useMemo, useState } from "react";
import type { TimelineSnapshot } from "@/lib/types";
import { sentimentColor, sentimentDisplay } from "@/lib/format";

const W = 760;
const H = 300;
const PAD_L = 48;
const PAD_R = 16;
const PAD_T = 16;
const PAD_B = 34;

export default function TimelineChart({ snapshots }: { snapshots: TimelineSnapshot[] }) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const { points, gridLines } = useMemo(() => {
    const maxVolRaw = Math.max(1, ...snapshots.map((s) => s.total_volume));
    // round the scale ceiling to a friendly number
    const mag = Math.pow(10, Math.floor(Math.log10(maxVolRaw)));
    const ceil = Math.ceil(maxVolRaw / mag) * mag;
    const innerW = W - PAD_L - PAD_R;
    const innerH = H - PAD_T - PAD_B;
    const n = snapshots.length;
    const pts = snapshots.map((s, i) => {
      const x = PAD_L + (n === 1 ? innerW / 2 : (i / (n - 1)) * innerW);
      const yVol = PAD_T + innerH - (s.total_volume / ceil) * innerH;
      // sentiment −1..1 mapped to the middle band (±35% of height around center)
      const sent = s.sentiment_score ?? 0;
      const ySent = PAD_T + innerH / 2 - sent * innerH * 0.35;
      return { x, yVol, ySent, snap: s };
    });
    const grid = [0, 0.25, 0.5, 0.75, 1].map((f) => ({
      y: PAD_T + (H - PAD_T - PAD_B) * (1 - f),
      label: Math.round(ceil * f),
    }));
    return { points: pts, gridLines: grid };
  }, [snapshots]);

  if (snapshots.length < 2) {
    return (
      <div
        className="grid place-items-center text-mute border border-dashed border-line"
        style={{ height: 220, borderRadius: "var(--radius)", fontSize: 12.5 }}
      >
        Not enough discovery runs yet to plot a timeline — run discovery a few
        times to build history.
      </div>
    );
  }

  const volLine = points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.yVol}`).join(" ");
  const volArea = `${volLine} L${points[points.length - 1].x},${H - PAD_B} L${points[0].x},${H - PAD_B} Z`;
  const sentLine = points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.ySent}`).join(" ");
  const zeroY = PAD_T + (H - PAD_T - PAD_B) / 2;
  const hover = hoverIdx != null ? points[hoverIdx] : null;

  const fmtDay = (iso: string) => {
    const d = new Date(iso);
    return `${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })}`;
  };
  const fmtFull = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  // sparse x labels — at most ~6
  const labelEvery = Math.max(1, Math.ceil(points.length / 6));

  return (
    <div style={{ position: "relative" }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: "100%", height: "auto", display: "block" }}
        onMouseLeave={() => setHoverIdx(null)}
      >
        {/* horizontal gridlines + volume axis labels */}
        {gridLines.map((g) => (
          <g key={g.y}>
            <line
              x1={PAD_L}
              x2={W - PAD_R}
              y1={g.y}
              y2={g.y}
              stroke="var(--border)"
              strokeDasharray="3 4"
              strokeWidth={1}
            />
            <text
              x={PAD_L - 8}
              y={g.y + 3.5}
              textAnchor="end"
              style={{ fontSize: 10, fill: "var(--textmute)", fontFamily: "var(--font-jetbrains-mono)" }}
            >
              {g.label}
            </text>
          </g>
        ))}
        {/* baseline */}
        <line x1={PAD_L} x2={W - PAD_R} y1={H - PAD_B} y2={H - PAD_B} stroke="var(--border2)" strokeWidth={1} />
        {/* sentiment zero line */}
        <line x1={PAD_L} x2={W - PAD_R} y1={zeroY} y2={zeroY} stroke="var(--warn)" strokeOpacity={0.35} strokeDasharray="2 5" strokeWidth={1} />

        {/* volume area + line */}
        <defs>
          <linearGradient id="volGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.28} />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <path d={volArea} fill="url(#volGrad)" />
        <path d={volLine} fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinejoin="round" />

        {/* sentiment line */}
        <path d={sentLine} fill="none" stroke="var(--warn)" strokeWidth={1.6} strokeLinejoin="round" />

        {/* x labels */}
        {points.map((p, i) =>
          i % labelEvery === 0 ? (
            <text
              key={i}
              x={p.x}
              y={H - PAD_B + 16}
              textAnchor="middle"
              style={{ fontSize: 10, fill: "var(--textmute)", fontFamily: "var(--font-jetbrains-mono)" }}
            >
              {fmtDay(p.snap.snapshot_at)}
            </text>
          ) : null,
        )}

        {/* hover crosshair + dots */}
        {hover && (
          <g>
            <line x1={hover.x} x2={hover.x} y1={PAD_T} y2={H - PAD_B} stroke="var(--textmute)" strokeWidth={1} strokeDasharray="3 3" />
            <circle cx={hover.x} cy={hover.yVol} r={4} fill="var(--accent)" stroke="var(--panel)" strokeWidth={2} />
            <circle cx={hover.x} cy={hover.ySent} r={3.5} fill="var(--warn)" stroke="var(--panel)" strokeWidth={2} />
          </g>
        )}

        {/* invisible hit rects */}
        {points.map((p, i) => {
          const half =
            points.length > 1 ? (points[1].x - points[0].x) / 2 : W / 2;
          return (
            <rect
              key={i}
              x={p.x - half}
              y={PAD_T}
              width={half * 2}
              height={H - PAD_T - PAD_B}
              fill="transparent"
              onMouseEnter={() => setHoverIdx(i)}
            />
          );
        })}
      </svg>

      {hover && (
        <div
          style={{
            position: "absolute",
            left: `${(hover.x / W) * 100}%`,
            top: 8,
            transform: hover.x > W * 0.65 ? "translateX(-105%)" : "translateX(12px)",
            background: "var(--panel)",
            border: "1px solid var(--border2)",
            borderRadius: "var(--radiussm)",
            boxShadow: "var(--shadowlg)",
            padding: "8px 11px",
            pointerEvents: "none",
            whiteSpace: "nowrap",
            zIndex: 5,
          }}
        >
          <div className="text-mute font-mono" style={{ fontSize: 10, marginBottom: 4 }}>
            {fmtFull(hover.snap.snapshot_at)}
          </div>
          <div className="flex items-center" style={{ gap: 6, fontSize: 11.5 }}>
            <span style={{ width: 8, height: 3, borderRadius: 2, background: "var(--accent)" }} />
            <span className="text-dim">Volume</span>
            <span className="text-ink" style={{ fontWeight: 600 }}>
              {hover.snap.total_volume}
            </span>
          </div>
          <div className="flex items-center" style={{ gap: 6, fontSize: 11.5 }}>
            <span style={{ width: 8, height: 3, borderRadius: 2, background: "var(--warn)" }} />
            <span className="text-dim">Sentiment</span>
            <span style={{ fontWeight: 600, color: sentimentColor(hover.snap.sentiment_score) }}>
              {sentimentDisplay(hover.snap.sentiment_score)}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
