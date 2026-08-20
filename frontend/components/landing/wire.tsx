"use client";

// The wire — the landing page's signature element.
//
// Real articles from the demo workspace ride a conveyor through the five
// pipeline stages the backend actually runs, and every value shown at a gate
// is a value the pipeline actually computed: the source it was crawled from,
// its identity key, the embedding width, the match score, the topic it landed
// under. Nothing is invented for effect.
//
// Note on what is NOT shown: the alerts API only returns articles that passed
// every gate, so no card is ever rejected mid-track. Rendering fake rejections
// would be the obvious way to dramatise fail-fast, and it would be a lie. The
// gate captions carry that story instead.

import { useEffect, useMemo, useReducer, useState } from "react";
import type { LandingFeed, LandingWireItem } from "@/lib/types";

const GATES = [
  { name: "Ingest", note: "Crawls every connected feed on a schedule." },
  { name: "Dedup", note: "Drops anything already seen, before it costs anything." },
  { name: "Embed", note: "Turns the text into a 768-dimension vector, locally." },
  { name: "Match", note: "Keeps it only if it sits close to a tracked topic." },
  { name: "Alert", note: "Summarises once, then delivers to everyone watching." },
] as const;

const LAST = GATES.length - 1;
const EXIT_STAGE = GATES.length; // rendered fading at the final position
const LANES = 3;
const TICK_MS = 1150;
const REFRESH_MS = 30_000;
const OUTPUT_KEEP = 4;
/** One stage per gate column. Paired with .lp-card's width in landing.css —
 *  change one and the cards stop sitting under their gate. */
const STAGE_STEP_PCT = 100 / GATES.length;

interface Card {
  uid: number;
  item: LandingWireItem;
  lane: number;
  stage: number;
}

interface State {
  cards: Card[];
  delivered: LandingWireItem[];
  cursor: number;
  uid: number;
}

function advance(state: State, source: LandingWireItem[]): State {
  if (source.length === 0) return state;

  const moved = state.cards.map((c) => ({ ...c, stage: c.stage + 1 }));
  const leaving = moved.filter((c) => c.stage > EXIT_STAGE);
  const cards = moved.filter((c) => c.stage <= EXIT_STAGE);

  // Admit into the first lane whose entry region is clear, so cards never
  // overlap even though they all move on the same clock.
  const busy = new Set(cards.filter((c) => c.stage <= 1).map((c) => c.lane));
  const lane = Array.from({ length: LANES }, (_, i) => i).find((l) => !busy.has(l));

  let { cursor, uid } = state;
  if (lane !== undefined) {
    cards.push({ uid, item: source[cursor % source.length], lane, stage: 0 });
    cursor += 1;
    uid += 1;
  }

  const delivered = leaving.length
    ? [...leaving.map((c) => c.item).reverse(), ...state.delivered].slice(0, OUTPUT_KEEP)
    : state.delivered;

  return { cards, delivered, cursor, uid };
}

/** Seeds a still frame: one card parked at three different gates. */
function seed(source: LandingWireItem[]): State {
  const cards = source.slice(0, LANES).map((item, i) => ({
    uid: i,
    item,
    lane: i,
    stage: [3, 1, 4][i] ?? 0,
  }));
  return {
    cards,
    delivered: source.slice(LANES, LANES + OUTPUT_KEEP),
    cursor: cards.length,
    uid: cards.length,
  };
}

/** The value this gate computed for this article. All of it comes from the API. */
function readout(item: LandingWireItem, stage: number): string {
  switch (stage) {
    case 0:
      return item.source;
    case 1:
      return `id ${item.key}`;
    case 2:
      return "768-d vector";
    case 3:
      return item.score != null ? `match ${item.score.toFixed(2)}` : "matched";
    default:
      return item.topic ? `→ ${item.topic}` : "delivered";
  }
}

function useMatches(query: string): boolean {
  const [matches, setMatches] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia(query);
    setMatches(mq.matches);
    const onChange = () => setMatches(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

function WireCard({ card }: { card: Card }) {
  const stage = Math.min(card.stage, LAST);
  const exiting = card.stage > LAST;
  return (
    <div
      className="lp-card lp-rise"
      data-state={exiting ? "leaving" : "travelling"}
      data-delivered={card.stage === LAST}
      style={{ left: `${0.6 + stage * STAGE_STEP_PCT}%` }}
    >
      <div className="lp-card-top">
        <span className="truncate">{card.item.source}</span>
      </div>
      <div className="lp-card-head">{card.item.headline}</div>
      <div className="lp-card-read">{readout(card.item, stage)}</div>
    </div>
  );
}

function CompactCard({ card }: { card: Card }) {
  const stage = Math.min(card.stage, LAST);
  return (
    <div
      className="lp-rise"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: 12,
        borderRadius: "var(--radius)",
        border: "1px solid var(--border)",
        background: "var(--panel)",
      }}
    >
      <div className="lp-card-top">
        <span className="truncate">{card.item.source}</span>
      </div>
      <div className="lp-card-head" style={{ fontSize: 12.5 }}>
        {card.item.headline}
      </div>
      <div className="lp-steps">
        {GATES.map((g, i) => (
          <span key={g.name} className="lp-step" data-done={i <= stage} />
        ))}
      </div>
      <div className="flex items-center justify-between">
        <span className="lp-eyebrow" style={{ letterSpacing: ".1em" }}>
          {GATES[stage].name}
        </span>
        <span className="lp-card-read">{readout(card.item, stage)}</span>
      </div>
    </div>
  );
}

export default function Wire({ initial }: { initial: LandingFeed }) {
  const compact = useMatches("(max-width: 899px)");
  const stillOnly = useMatches("(prefers-reduced-motion: reduce)");

  // Server-rendered on first paint, then refreshed so a tab left open keeps
  // showing what the pipeline is handling now rather than an hour ago.
  const [feed, setFeed] = useState(initial);
  const { articles, live, matchedTotal } = feed;

  useEffect(() => {
    let alive = true;
    const id = setInterval(async () => {
      try {
        const res = await fetch("/api/public/stream", { cache: "no-store" });
        if (!res.ok) return;
        const next: LandingFeed = await res.json();
        // Keep the last good payload on a blank response — the wire going
        // empty mid-scroll looks broken, not honest.
        if (alive && next.articles.length > 0) setFeed(next);
      } catch {
        // offline or navigating away; the next tick retries
      }
    }, REFRESH_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  // Lazy init — seed() runs once, on mount. After that the reducer always
  // reads the freshest `articles` through the closure, so a poll that swaps
  // the source list takes effect on the next tick without a remount.
  const [state, tick] = useReducer(
    (s: State) => advance(s, articles),
    initial.articles,
    seed,
  );

  useEffect(() => {
    if (stillOnly || articles.length === 0) return;
    const id = setInterval(tick, TICK_MS);
    return () => clearInterval(id);
  }, [stillOnly, articles.length]);

  const hot = useMemo(
    () => new Set(state.cards.map((c) => Math.min(c.stage, LAST))),
    [state.cards],
  );

  return (
    <div className="lp-wire">
      <div className="lp-wire-bar">
        <span className="lp-pill" data-live={live}>
          <span className="lp-pill-dot" />
          {live ? "On the wire" : "Backend offline"}
        </span>
        <span className="lp-eyebrow truncate" style={{ letterSpacing: ".08em" }}>
          {live
            ? "Real articles, real scores, from the demo workspace"
            : "No articles to show — the backend isn't answering"}
        </span>
        <span style={{ flex: 1 }} />
        {matchedTotal > 0 && (
          <span
            className="lp-mono"
            style={{ fontSize: 11, color: "var(--textdim)" }}
          >
            {matchedTotal.toLocaleString()} matched
          </span>
        )}
      </div>

      {/* The gates are worth showing even with nothing travelling them — they
          are the argument. Only the lane area swaps for the empty state. */}
      {!compact && (
        <div className="lp-gates">
          {GATES.map((g, i) => (
            <div key={g.name} className="lp-gate" data-hot={hot.has(i)}>
              <span className="lp-gate-name">{g.name}</span>
              <span className="lp-gate-note">{g.note}</span>
            </div>
          ))}
        </div>
      )}

      {articles.length === 0 ? (
        <div style={{ padding: "30px 16px 34px", textAlign: "center" }}>
          <p style={{ fontSize: 12, lineHeight: 1.6, color: "var(--textmute)" }}>
            Nothing on the wire right now. Articles appear here as they clear
            each stage, once the ingestion workers are running.
          </p>
        </div>
      ) : compact ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: 14 }}>
          {state.cards
            .filter((c) => c.stage <= LAST)
            .slice(0, 2)
            .map((c) => (
              <CompactCard key={c.uid} card={c} />
            ))}
        </div>
      ) : (
        <div className="lp-lanes">
          {Array.from({ length: LANES }, (_, lane) => (
            <div key={lane} className="lp-lane">
              {state.cards
                .filter((c) => c.lane === lane)
                .map((c) => (
                  <WireCard key={c.uid} card={c} />
                ))}
            </div>
          ))}
        </div>
      )}

      {state.delivered.length > 0 && (
        <div className="lp-out">
          <span className="lp-eyebrow">Delivered</span>
          {state.delivered.map((item) => (
            <a
              key={item.id}
              href={item.url}
              target="_blank"
              rel="noopener noreferrer"
              className="lp-out-row"
            >
              <span
                style={{
                  width: 5,
                  height: 5,
                  borderRadius: "50%",
                  background: "var(--pos)",
                  flex: "none",
                }}
              />
              <span
                className="truncate"
                style={{ flex: 1, fontSize: 11.5, color: "var(--textdim)" }}
              >
                {item.headline}
              </span>
              {item.topic && (
                <span className="lp-chip" data-tone="new">
                  {item.topic}
                </span>
              )}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
