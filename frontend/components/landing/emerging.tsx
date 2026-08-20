"use client";

// Emerging stories — the second half of the pitch. The wire shows the system
// filtering what you asked for; this shows it naming things you didn't.
//
// Every cluster here is a real sub-theme the discovery run produced for the
// demo workspace: the label and description were written by the model, the
// volume and growth are measured against the previous run.

import Reveal from "@/components/landing/reveal";
import type { LandingNarrative } from "@/lib/types";

const TICK_CAP = 26;

/** Status → chip tone. Mirrors how the workspace colours the same states. */
function tone(status: string): string {
  if (status === "new" || status === "revival") return "new";
  if (status === "growing") return "up";
  if (status === "declining") return "warn";
  return "flat";
}

function growthLabel(n: LandingNarrative): string | null {
  if (n.status === "new") return "first appearance";
  if (n.status === "revival") return "back after a lull";
  if (n.growth == null) return null;
  const pct = Math.round(n.growth * 100);
  return `${pct > 0 ? "+" : ""}${pct}% vs last run`;
}

function NarrativeCard({ n, index }: { n: LandingNarrative; index: number }) {
  const ticks = Math.max(3, Math.min(n.volume, TICK_CAP));
  return (
    <Reveal delay={index * 70}>
      <article className="lp-nar">
        <div className="flex items-center justify-between" style={{ gap: 8 }}>
          <span className="lp-eyebrow truncate">{n.topic}</span>
          <span className="lp-chip" data-tone={tone(n.status)}>
            {n.status}
          </span>
        </div>

        <h3 className="lp-nar-label">{n.label}</h3>

        {n.description && (
          <p
            style={{
              fontSize: 12,
              lineHeight: 1.5,
              color: "var(--textmute)",
              display: "-webkit-box",
              WebkitLineClamp: 3,
              WebkitBoxOrient: "vertical",
              overflow: "hidden",
            }}
          >
            {n.description}
          </p>
        )}

        {/* One tick per article in the cluster, capped. The bar chart *is*
            the count — no separate decorative sparkline. */}
        <div className="lp-ticks" aria-hidden>
          {Array.from({ length: ticks }, (_, i) => (
            <span
              key={i}
              className="lp-tick"
              style={{
                height: `${38 + ((i * 37) % 62)}%`,
                animationDelay: `${index * 70 + i * 18}ms`,
              }}
            />
          ))}
        </div>

        <div
          className="flex items-baseline border-t border-line"
          style={{ gap: 8, paddingTop: 10 }}
        >
          <span
            className="lp-mono"
            style={{ fontSize: 15, fontWeight: 600, color: "var(--text)" }}
          >
            {n.volume.toLocaleString()}
          </span>
          <span className="lp-eyebrow" style={{ letterSpacing: ".08em" }}>
            {n.volume === 1 ? "article" : "articles"}
          </span>
          <span style={{ flex: 1 }} />
          {growthLabel(n) && (
            <span style={{ fontSize: 10.5, color: "var(--textmute)" }}>
              {growthLabel(n)}
            </span>
          )}
        </div>

        {n.lead && (
          <div
            style={{
              fontSize: 11,
              lineHeight: 1.4,
              color: "var(--textdim)",
              borderLeft: "2px solid var(--accentsoft)",
              paddingLeft: 9,
            }}
          >
            {n.lead.headline}
            {n.lead.source && (
              <span className="lp-mono" style={{ color: "var(--textmute)" }}>
                {" "}
                · {n.lead.source}
              </span>
            )}
          </div>
        )}
      </article>
    </Reveal>
  );
}

export default function Emerging({
  narratives,
}: {
  narratives: LandingNarrative[];
}) {
  if (narratives.length === 0) {
    return (
      <div
        className="lp-nar"
        style={{ alignItems: "center", textAlign: "center", padding: 40 }}
      >
        <p style={{ fontSize: 13, color: "var(--textmute)", maxWidth: 340 }}>
          No clusters to show right now. The next discovery run will fill this
          in — open the demo workspace to trigger one.
        </p>
      </div>
    );
  }

  return (
    <div className="lp-narratives">
      {narratives.map((n, i) => (
        <NarrativeCard key={n.id} n={n} index={i} />
      ))}
    </div>
  );
}
