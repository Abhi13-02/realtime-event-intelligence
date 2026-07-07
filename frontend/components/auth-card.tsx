"use client";

// Shared full-viewport auth screen chrome per handoff: centered 392px card
// over a soft radial accent glow, logo lockup above.

import type { ReactNode } from "react";

export default function AuthCard({ children }: { children: ReactNode }) {
  return (
    <div
      className="grid place-items-center"
      style={{
        minHeight: "100vh",
        background: "var(--bg)",
        padding: 24,
        position: "relative",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "radial-gradient(600px 400px at 50% -10%, var(--accentsoft), transparent 70%)",
          pointerEvents: "none",
        }}
      />
      <div className="w-full nifade" style={{ maxWidth: 392, position: "relative" }}>
        <div
          className="flex items-center justify-center"
          style={{ gap: 11, marginBottom: 30 }}
        >
          <div
            className="grid place-items-center bg-accent text-accentfg"
            style={{
              width: 34,
              height: 34,
              borderRadius: 9,
              fontWeight: 700,
              fontSize: 18,
              boxShadow: "0 4px 16px var(--accentsoft)",
            }}
          >
            N
          </div>
          <div>
            <div
              className="text-ink"
              style={{ fontSize: 16, fontWeight: 650, letterSpacing: "-.02em", lineHeight: 1.1 }}
            >
              Narrative Intelligence
            </div>
            <div
              className="text-mute uppercase"
              style={{ fontSize: 11, letterSpacing: ".04em" }}
            >
              Signal monitoring platform
            </div>
          </div>
        </div>
        <div
          className="bg-panel border border-line"
          style={{
            borderRadius: "var(--radiuslg)",
            padding: "28px 26px",
            boxShadow: "var(--shadow)",
          }}
        >
          {children}
        </div>
        <div className="text-center text-mute" style={{ marginTop: 18, fontSize: 11.5 }}>
          Protected workspace
        </div>
      </div>
    </div>
  );
}
