"use client";

// Admin › Data — parity with the old panel: global sub-theme list
// (delete one / wipe all) and article inventory (summaries, pipeline
// status, topics, wipe all).

import { useState } from "react";
import { Btn, Flash, StatusChip } from "@/components/ui";
import { adminApi } from "@/lib/api";
import type { AdminArticles, AdminSubTheme } from "@/lib/types";
import { timeAgo } from "@/lib/format";

type FlashMsg = { text: string; type: "ok" | "err" } | null;

export default function DataTab() {
  const [subthemes, setSubthemes] = useState<AdminSubTheme[] | null>(null);
  const [loadingST, setLoadingST] = useState(false);
  const [articles, setArticles] = useState<AdminArticles | null>(null);
  const [loadingAR, setLoadingAR] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [msg, setMsg] = useState<FlashMsg>(null);

  const flash = (text: string, type: "ok" | "err" = "ok") => {
    setMsg({ text, type });
    setTimeout(() => setMsg(null), 4000);
  };

  const loadSubthemes = async () => {
    setLoadingST(true);
    try {
      setSubthemes(await adminApi.getSubthemes());
    } catch {
      flash("Failed", "err");
    } finally {
      setLoadingST(false);
    }
  };

  const loadArticles = async () => {
    setLoadingAR(true);
    try {
      setArticles(await adminApi.getArticles());
    } catch {
      flash("Failed", "err");
    } finally {
      setLoadingAR(false);
    }
  };

  const deleteOne = async (id: string) => {
    if (!window.confirm("Delete this sub-theme?")) return;
    try {
      await adminApi.deleteSubtheme(id);
      setSubthemes((prev) => prev?.filter((s) => s.id !== id) ?? null);
      flash("Sub-theme deleted.");
    } catch {
      flash("Delete failed", "err");
    }
  };

  const wipe = async (kind: "articles" | "subthemes") => {
    if (!window.confirm(`Delete ALL ${kind}? This cannot be undone.`)) return;
    setDeleting(kind);
    try {
      if (kind === "articles") {
        await adminApi.deleteArticles();
        setArticles(null);
      } else {
        await adminApi.deleteSubthemes();
        setSubthemes(null);
      }
      flash(`All ${kind} deleted.`);
    } catch {
      flash("Delete failed", "err");
    } finally {
      setDeleting(null);
    }
  };

  return (
    <div className="flex flex-col" style={{ gap: 16 }}>
      <Flash msg={msg} />

      {/* sub-themes */}
      <div className="bg-panel border border-line" style={{ borderRadius: "var(--radius)", padding: 18 }}>
        <div className="flex items-center justify-between" style={{ marginBottom: 12 }}>
          <span className="eyebrow" style={{ fontSize: 11 }}>Sub-themes (global)</span>
          <div className="flex" style={{ gap: 6 }}>
            <Btn onClick={loadSubthemes} disabled={loadingST}>
              {loadingST ? "Loading…" : "Load"}
            </Btn>
            <Btn
              variant="danger"
              onClick={() => wipe("subthemes")}
              disabled={deleting === "subthemes"}
              style={{ border: "1px solid var(--neg)" }}
            >
              {deleting === "subthemes" ? "Deleting…" : "Wipe all"}
            </Btn>
          </div>
        </div>
        {!subthemes ? (
          <div className="text-center text-mute" style={{ padding: "18px 0", fontSize: 12 }}>
            Load to view sub-themes.
          </div>
        ) : (
          <div className="flex flex-col" style={{ gap: 4, maxHeight: 340, overflowY: "auto", paddingRight: 4 }}>
            {subthemes.map((s) => (
              <div
                key={s.id}
                className="flex items-center justify-between border-b border-line last:border-0"
                style={{ padding: "8px 0", gap: 10 }}
              >
                <div className="flex-1 min-w-0">
                  <div className="text-ink truncate" style={{ fontSize: 12.5 }}>{s.label}</div>
                  {s.topic && (
                    <div className="text-mute truncate" style={{ fontSize: 10 }}>{s.topic}</div>
                  )}
                </div>
                <div className="flex items-center" style={{ gap: 10, flex: "none" }}>
                  <StatusChip status={s.status} />
                  <span className="font-mono" style={{ fontSize: 10, color: "var(--accent2)", width: 48, textAlign: "right" }}>
                    {s.total_volume ?? 0} vol
                  </span>
                  <button
                    onClick={() => deleteOne(s.id)}
                    className="text-mute hover:text-neg transition-colors"
                    style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", background: "transparent", border: "none" }}
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* articles */}
      <div className="bg-panel border border-line" style={{ borderRadius: "var(--radius)", padding: 18 }}>
        <div className="flex items-center justify-between" style={{ marginBottom: 12 }}>
          <span className="eyebrow" style={{ fontSize: 11 }}>Articles</span>
          <div className="flex" style={{ gap: 6 }}>
            <Btn onClick={loadArticles} disabled={loadingAR}>
              {loadingAR ? "Loading…" : "Load"}
            </Btn>
            <Btn
              variant="danger"
              onClick={() => wipe("articles")}
              disabled={deleting === "articles"}
              style={{ border: "1px solid var(--neg)" }}
            >
              {deleting === "articles" ? "Deleting…" : "Wipe all"}
            </Btn>
          </div>
        </div>
        {!articles ? (
          <div className="text-center text-mute" style={{ padding: "18px 0", fontSize: 12 }}>
            Load to view articles.
          </div>
        ) : (
          <>
            <div style={{ fontSize: 16, fontWeight: 600, color: "var(--accent2)", marginBottom: 12 }}>
              {articles.total_count} total articles
            </div>
            <div className="flex flex-col" style={{ gap: 10, maxHeight: 520, overflowY: "auto", paddingRight: 4 }}>
              {articles.articles?.slice(0, 100).map((a) => (
                <div
                  key={a.id}
                  className="bg-bg2 border border-line hover:border-line2 transition-colors"
                  style={{ padding: 12, borderRadius: "var(--radiussm)" }}
                >
                  <div className="flex items-start justify-between" style={{ gap: 10, marginBottom: 6 }}>
                    <a
                      href={a.url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-ink hover:text-accent2 transition-colors"
                      style={{ fontSize: 12.5, fontWeight: 550, lineHeight: 1.35 }}
                    >
                      {a.headline}
                    </a>
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 600,
                        padding: "2px 8px",
                        borderRadius: 99,
                        flex: "none",
                        color: a.pipeline_status === "processed" ? "var(--pos)" : "var(--warn)",
                        background: a.pipeline_status === "processed" ? "var(--possoft)" : "var(--warnsoft)",
                      }}
                    >
                      {a.pipeline_status}
                    </span>
                  </div>
                  <div className="flex items-center flex-wrap" style={{ gap: 8, marginBottom: 6 }}>
                    <span
                      style={{ fontSize: 10, fontWeight: 600, color: "var(--accent2)", background: "var(--accentsoft)", padding: "2px 8px", borderRadius: 99 }}
                    >
                      {a.source_name}
                    </span>
                    <span className="text-mute" style={{ fontSize: 10 }}>
                      {timeAgo(a.published_at ?? a.crawled_at)}
                    </span>
                    {a.topics?.map((t, ti) => (
                      <span
                        key={ti}
                        style={{ fontSize: 10, fontWeight: 600, color: "var(--pos)", background: "var(--possoft)", padding: "2px 8px", borderRadius: 99 }}
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                  <div
                    className="text-mute"
                    style={{
                      fontSize: 11.5,
                      lineHeight: 1.5,
                      display: "-webkit-box",
                      WebkitLineClamp: 3,
                      WebkitBoxOrient: "vertical",
                      overflow: "hidden",
                      marginBottom: 6,
                    }}
                  >
                    {a.summary || "No summary available."}
                  </div>
                  <div className="text-mute font-mono" style={{ fontSize: 9 }}>
                    ID: {a.id}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
