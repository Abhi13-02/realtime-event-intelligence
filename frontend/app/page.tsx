// Public landing page.
//
// Server-rendered so the wire and the narrative cards are in the HTML on first
// paint — the whole pitch is "this is running right now", and a page that
// arrives empty and fills in later undercuts it.

import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight, Radio } from "lucide-react";
import { auth } from "@/auth";
import Emerging from "@/components/landing/emerging";
import Reveal from "@/components/landing/reveal";
import Wire from "@/components/landing/wire";
import { getLandingFeed } from "@/lib/landing-data";
import "./landing.css";

export const metadata: Metadata = {
  title: "Narrative Intelligence — know before it's news",
  description:
    "Watches news feeds and Hacker News in real time, keeps only what matches your topics, and finds the stories forming before anyone names them.",
};

export const dynamic = "force-dynamic";

const CHANNELS = [
  {
    name: "In the browser",
    body: "The feed updates while you're looking at it. No refresh, no polling badge.",
  },
  {
    name: "One email a day",
    body: "A single digest at a fixed hour — not one message per article.",
  },
  {
    name: "SMS",
    body: "For the handful of topics where the difference is minutes, not hours.",
  },
];

const STACK = [
  "FastAPI",
  "Kafka",
  "Celery",
  "PostgreSQL + pgvector",
  "all-mpnet-base-v2",
  "Gemini 1.5 Flash",
];

export default async function LandingPage() {
  const [session, feed] = await Promise.all([auth(), getLandingFeed()]);
  const signedIn = Boolean(session?.user);

  return (
    <div className="lp">
      <nav className="lp-nav" data-stuck="true">
        <div className="lp-shell flex w-full items-center" style={{ gap: 12 }}>
          <div className="flex items-center" style={{ gap: 9 }}>
            <span
              className="grid place-items-center bg-accent text-accentfg"
              style={{ width: 23, height: 23, borderRadius: 7, fontWeight: 700, fontSize: 13 }}
            >
              N
            </span>
            <span style={{ fontSize: 13, fontWeight: 620, letterSpacing: "-.01em" }}>
              Narrative Intelligence
            </span>
          </div>
          <span style={{ flex: 1 }} />
          {signedIn ? (
            <Link href="/feed" className="lp-btn lp-btn-primary" style={{ height: 34 }}>
              Open workspace
              <ArrowRight size={14} strokeWidth={2} />
            </Link>
          ) : (
            <>
              <Link
                href="/login"
                className="lp-btn lp-btn-ghost"
                style={{ height: 34, border: "none" }}
              >
                Sign in
              </Link>
              <Link href="/register" className="lp-btn lp-btn-primary" style={{ height: 34 }}>
                Create account
              </Link>
            </>
          )}
        </div>
      </nav>

      {/* ── hero + the wire ───────────────────────────────────────── */}
      <header className="lp-hero">
        <div className="lp-shell">
          <div className="lp-rise" style={{ animationDelay: "40ms" }}>
            <span className="lp-pill" data-live={feed.live}>
              <span className="lp-pill-dot" />
              {feed.live ? "Live now" : "Standing by"}
            </span>
          </div>

          <h1
            className="lp-display lp-rise"
            style={{ animationDelay: "120ms", margin: "26px 0 0" }}
          >
            Every story starts
            <br />
            as <span className="lp-token">noise</span>.
          </h1>

          <p
            className="lp-lede lp-rise"
            style={{ animationDelay: "220ms", margin: "26px 0 0" }}
          >
            This reads news feeds and Hacker News all day, throws out
            everything that isn&apos;t yours, and tells you about what&apos;s
            left — usually within five minutes of it going up.
          </p>

          <div
            className="flex flex-wrap lp-rise"
            style={{ gap: 10, marginTop: 30, animationDelay: "300ms" }}
          >
            <Link
              href={signedIn ? "/feed" : "/login"}
              className="lp-btn lp-btn-primary"
            >
              {signedIn ? "Open workspace" : "Explore the live demo"}
              <ArrowRight size={15} strokeWidth={2} />
            </Link>
            <Link href="/register" className="lp-btn lp-btn-ghost">
              Create an account
            </Link>
          </div>

          <div
            className="lp-rise"
            style={{ animationDelay: "420ms", marginTop: 52 }}
          >
            <Wire initial={feed} />
          </div>

          {/* The caption does real work: it tells you what you're looking at,
              and it's where the fail-fast argument actually lands. */}
          <p
            className="lp-rise"
            style={{
              animationDelay: "520ms",
              marginTop: 16,
              fontSize: 11.5,
              lineHeight: 1.6,
              color: "var(--textmute)",
              maxWidth: "68ch",
            }}
          >
            Each card is a real article from the demo workspace, showing the
            value every stage computed for it. Only survivors are visible here —
            the ones killed at dedup or match never became alerts, and never
            cost a summarisation call. That order is the whole design.
          </p>
        </div>
      </header>

      {/* ── emerging stories ──────────────────────────────────────── */}
      <section className="lp-section">
        <div className="lp-shell">
          <div className="lp-section-head">
            <Reveal>
              <span className="lp-eyebrow">Discovery</span>
            </Reveal>
            <Reveal delay={60}>
              <h2 className="lp-h2">You don&apos;t tell it what to look for.</h2>
            </Reveal>
            <Reveal delay={120}>
              <p className="lp-lede">
                Give it a topic and it reads everything nearby, clusters what it
                finds, and names the story itself. These are real clusters from
                the demo workspace&apos;s last discovery run — labels and all.
              </p>
            </Reveal>
          </div>
          <Emerging narratives={feed.narratives} />
          <Reveal delay={140}>
            <div style={{ marginTop: 24 }}>
              <Link
                href={signedIn ? "/topics" : "/login"}
                className="lp-btn lp-btn-ghost"
              >
                Track one of these
                <ArrowRight size={15} strokeWidth={2} />
              </Link>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ── delivery ──────────────────────────────────────────────── */}
      <section className="lp-section">
        <div className="lp-shell">
          <div className="lp-section-head">
            <Reveal>
              <span className="lp-eyebrow">Delivery</span>
            </Reveal>
            <Reveal delay={60}>
              <h2 className="lp-h2">Three ways to hear about it.</h2>
            </Reveal>
          </div>

          <div className="lp-channels">
            {CHANNELS.map((c, i) => (
              <Reveal key={c.name} delay={i * 70}>
                <div className="lp-channel">
                  <div className="flex items-center" style={{ gap: 8, marginBottom: 9 }}>
                    <Radio size={14} strokeWidth={1.7} style={{ color: "var(--accent2)" }} />
                    <span style={{ fontSize: 13, fontWeight: 620 }}>{c.name}</span>
                  </div>
                  <p style={{ fontSize: 12, lineHeight: 1.55, color: "var(--textmute)" }}>
                    {c.body}
                  </p>
                </div>
              </Reveal>
            ))}
          </div>

          <Reveal delay={200}>
            <div
              className="flex flex-wrap items-center"
              style={{ gap: 8, marginTop: 28 }}
            >
              <span className="lp-eyebrow" style={{ marginRight: 4 }}>
                Built on
              </span>
              {STACK.map((s) => (
                <span key={s} className="lp-chip">
                  {s}
                </span>
              ))}
            </div>
          </Reveal>
        </div>
      </section>

      {/* ── close ─────────────────────────────────────────────────── */}
      <section className="lp-section">
        <div className="lp-shell">
          <Reveal>
            <h2 className="lp-h2" style={{ maxWidth: "18ch" }}>
              Point it at something you care about.
            </h2>
          </Reveal>
          <Reveal delay={70}>
            <p className="lp-lede" style={{ marginTop: 16 }}>
              The demo workspace is already tracking a few topics and has
              articles and clusters in it. Nothing to set up — just look around.
            </p>
          </Reveal>
          <Reveal delay={140}>
            <div className="flex flex-wrap" style={{ gap: 10, marginTop: 28 }}>
              <Link
                href={signedIn ? "/feed" : "/login"}
                className="lp-btn lp-btn-primary"
              >
                {signedIn ? "Open workspace" : "Explore the live demo"}
                <ArrowRight size={15} strokeWidth={2} />
              </Link>
              <Link href="/register" className="lp-btn lp-btn-ghost">
                Create an account
              </Link>
            </div>
          </Reveal>
        </div>
      </section>

      <footer
        style={{
          borderTop: "1px solid var(--border)",
          padding: "22px 0",
        }}
      >
        <div
          className="lp-shell flex flex-wrap items-center"
          style={{ gap: 12 }}
        >
          <span className="lp-eyebrow">Narrative Intelligence</span>
          <span style={{ flex: 1 }} />
          <Link
            href="/login"
            style={{ fontSize: 11.5, color: "var(--textmute)" }}
          >
            Sign in
          </Link>
          <Link
            href="/register"
            style={{ fontSize: 11.5, color: "var(--textmute)" }}
          >
            Create account
          </Link>
        </div>
      </footer>
    </div>
  );
}
