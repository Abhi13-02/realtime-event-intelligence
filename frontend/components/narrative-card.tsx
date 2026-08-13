"use client";

// Narrative cluster card per handoff: label + NEW/REVIVAL badge, status
// chip, description, bipolar sentiment bar, volume + growth stats,
// representative-article strip. Click navigates to the narrative timeline.

import { NewBadge, RevivalBadge, StatusChip } from "@/components/ui";
import type { SubTheme } from "@/lib/types";
import {
  SOCIAL_SIGNALS_ENABLED,
  formatVolume,
  growthColor,
  growthDisplay,
  sentimentColor,
  sentimentDisplay,
} from "@/lib/format";

export default function NarrativeCard({
  theme,
  onOpen,
}: {
  theme: SubTheme;
  onOpen: () => void;
}) {
  const sentPct = theme.sentiment_score != null ? theme.sentiment_score * 100 : 0;
  const fillWidth = Math.min(Math.abs(sentPct) / 2, 50);
  // Badges follow `status`, the single source of truth, rather than the
  // is_new/is_revival booleans the API used to infer from snapshot arithmetic.
  const isNew = theme.status === "new" || theme.is_new;
  const isRevival = theme.status === "revival" || theme.is_revival;

  return (
    <div
      onClick={onOpen}
      className="bg-panel border border-line hover:border-line2 cursor-pointer flex flex-col transition-colors nifade"
      style={{ borderRadius: "var(--radius)", padding: 15, gap: 11 }}
    >
      <div className="flex items-start justify-between" style={{ gap: 8 }}>
        <div className="flex items-center flex-wrap min-w-0" style={{ gap: 7 }}>
          <span className="text-ink" style={{ fontSize: 13.5, fontWeight: 600, letterSpacing: "-.01em" }}>
            {theme.label ?? "Unlabeled cluster"}
          </span>
          {isNew && <NewBadge />}
          {isRevival && <RevivalBadge />}
        </div>
        <StatusChip status={theme.status} />
      </div>

      {theme.description && (
        <div
          className="text-mute"
          style={{
            fontSize: 11.5,
            lineHeight: 1.45,
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
          }}
        >
          {theme.description}
        </div>
      )}

      {SOCIAL_SIGNALS_ENABLED && (
        <div>
          <div className="flex items-center justify-between" style={{ marginBottom: 6 }}>
            <span className="eyebrow">Sentiment</span>
            <span style={{ fontSize: 12, fontWeight: 600, color: sentimentColor(theme.sentiment_score) }}>
              {sentimentDisplay(theme.sentiment_score)}
            </span>
          </div>
          {/* bipolar bar: zero mark centered, fill extends left/right */}
          <div style={{ position: "relative", height: 5, borderRadius: 99, background: "var(--panel2)" }}>
            <div
              style={{
                position: "absolute",
                left: "50%",
                top: -2,
                bottom: -2,
                width: 1,
                background: "var(--border2)",
              }}
            />
            <div
              style={{
                position: "absolute",
                top: 0,
                bottom: 0,
                left: sentPct >= 0 ? "50%" : `${50 - fillWidth}%`,
                width: `${fillWidth}%`,
                borderRadius: 99,
                background: sentimentColor(theme.sentiment_score),
              }}
            />
          </div>
        </div>
      )}

      <div className="flex border-t border-line" style={{ gap: 16, paddingTop: 11 }}>
        <div>
          <div className="text-ink" style={{ fontSize: 14, fontWeight: 600, lineHeight: 1 }}>
            {formatVolume(theme.total_volume)}
          </div>
          <div className="eyebrow" style={{ letterSpacing: ".04em", marginTop: 3 }}>
            volume
          </div>
        </div>
        <div>
          {/* The growth cell always shows the number. It used to be overwritten
              with the literal string "NEW" whenever is_new was set, which meant
              a cluster could never show both its badge and its percentage.
              The badge above carries "new"; this carries the measurement, and
              renders an em dash when there is genuinely no baseline. */}
          <div
            style={{
              fontSize: 14,
              fontWeight: 600,
              lineHeight: 1,
              color: growthColor(theme.status, theme.growth_pct),
            }}
          >
            {growthDisplay(theme.growth_pct)}
          </div>
          <div className="eyebrow" style={{ letterSpacing: ".04em", marginTop: 3 }}>
            growth
          </div>
        </div>
      </div>

      {theme.representative_article && (
        <div
          className="flex items-center bg-bg2 border border-line"
          style={{ gap: 9, borderRadius: "var(--radiussm)", padding: 8 }}
        >
          {theme.representative_article.image_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={theme.representative_article.image_url}
              alt=""
              className="object-cover"
              style={{ width: 46, height: 46, flex: "none", borderRadius: "var(--radiussm)", border: "1px solid var(--border)" }}
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = "none";
              }}
            />
          ) : (
            <div
              className="thumb-stripes"
              style={{ width: 46, height: 46, flex: "none", borderRadius: "var(--radiussm)" }}
            />
          )}
          <div className="flex-1 min-w-0">
            <div
              className="text-dim"
              style={{
                fontSize: 11,
                fontWeight: 500,
                lineHeight: 1.3,
                overflow: "hidden",
                display: "-webkit-box",
                WebkitLineClamp: 2,
                WebkitBoxOrient: "vertical",
              }}
            >
              {theme.representative_article.headline}
            </div>
            {theme.representative_article.source_name && (
              <div className="text-mute" style={{ fontSize: 10, marginTop: 3 }}>
                {theme.representative_article.source_name}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
