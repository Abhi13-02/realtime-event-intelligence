"use client";

// Admin › Ingestion — parity with the old panel: source enable/disable,
// poll interval (minutes) + crawl limit editing, per-source RSS feed
// toggles, and subreddit CRUD (name/limit/sort, on/off, remove).

import { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import { Btn, Flash, Input } from "@/components/ui";
import { adminApi } from "@/lib/api";
import type { IngestionSource, SourceFeed, Subreddit } from "@/lib/types";

type FlashMsg = { text: string; type: "ok" | "err" } | null;

export default function IngestionTab() {
  const [sources, setSources] = useState<IngestionSource[] | null>(null);
  const [selectedSource, setSelectedSource] = useState<IngestionSource | null>(null);
  const [feeds, setFeeds] = useState<SourceFeed[] | null>(null);
  const [subreddits, setSubreddits] = useState<Subreddit[] | null>(null);
  const [newSub, setNewSub] = useState({ name: "", limit: "10", sort: "new" });
  const [msg, setMsg] = useState<FlashMsg>(null);

  const flash = (text: string, type: "ok" | "err" = "ok") => {
    setMsg({ text, type });
    setTimeout(() => setMsg(null), 4000);
  };

  const loadSources = () =>
    adminApi
      .getIngestionSources()
      .then(setSources)
      .catch(() => flash("Failed to load sources", "err"));
  const loadSubreddits = () =>
    adminApi
      .getSubreddits()
      .then(setSubreddits)
      .catch(() => flash("Failed to load subreddits", "err"));

  useEffect(() => {
    loadSources();
    loadSubreddits();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggleSource = async (s: IngestionSource) => {
    try {
      await adminApi.updateSource(s.id, { is_active: !s.is_active });
      setSources((prev) =>
        prev?.map((x) => (x.id === s.id ? { ...x, is_active: !s.is_active } : x)) ?? null,
      );
      flash(`${s.name} ${!s.is_active ? "enabled" : "disabled"}`);
    } catch {
      flash("Update failed", "err");
    }
  };

  const updateInterval = async (s: IngestionSource, minutes: string) => {
    const v = parseInt(minutes, 10);
    if (!Number.isFinite(v) || v <= 0) return;
    try {
      await adminApi.updateSource(s.id, { poll_interval: v * 60 });
      flash("Interval updated");
    } catch {
      flash("Update failed", "err");
    }
  };

  const updateLimit = async (s: IngestionSource, limit: string) => {
    const v = parseInt(limit, 10);
    if (!Number.isFinite(v) || v <= 0) return;
    try {
      await adminApi.updateSource(s.id, { articles_per_crawl: v });
      flash("Limit updated");
    } catch {
      flash("Update failed", "err");
    }
  };

  const openFeeds = async (s: IngestionSource) => {
    setSelectedSource(s);
    setFeeds(null);
    try {
      setFeeds(await adminApi.getSourceFeeds(s.id));
    } catch {
      flash("Failed to load feeds", "err");
    }
  };

  const toggleFeed = async (f: SourceFeed) => {
    try {
      await adminApi.updateFeed(f.id, { is_active: !f.is_active });
      setFeeds((prev) =>
        prev?.map((x) => (x.id === f.id ? { ...x, is_active: !f.is_active } : x)) ?? null,
      );
    } catch {
      flash("Update failed", "err");
    }
  };

  const toggleSubreddit = async (sub: Subreddit) => {
    try {
      await adminApi.updateSubreddit(sub.id, { is_active: !sub.is_active });
      setSubreddits((prev) =>
        prev?.map((x) => (x.id === sub.id ? { ...x, is_active: !sub.is_active } : x)) ?? null,
      );
    } catch {
      flash("Update failed", "err");
    }
  };

  const deleteSubreddit = async (id: string) => {
    if (!window.confirm("Remove this subreddit?")) return;
    try {
      await adminApi.deleteSubreddit(id);
      setSubreddits((prev) => prev?.filter((x) => x.id !== id) ?? null);
      flash("Subreddit removed");
    } catch {
      flash("Delete failed", "err");
    }
  };

  const addSubreddit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await adminApi.addSubreddit({
        name: newSub.name,
        limit_per_crawl: parseInt(newSub.limit, 10) || 10,
        sort: newSub.sort,
      });
      flash(`r/${newSub.name} added`);
      setNewSub({ name: "", limit: "10", sort: "new" });
      loadSubreddits();
    } catch {
      flash("Add failed", "err");
    }
  };

  const numInput = (defaultValue: number | null, onBlur: (v: string) => void) => (
    <input
      type="number"
      defaultValue={defaultValue ?? ""}
      onBlur={(e) => onBlur(e.target.value)}
      className="bg-bg2 text-ink border border-line2 outline-none focus:border-accent font-mono"
      style={{ width: 56, padding: "3px 6px", borderRadius: "var(--radiussm)", fontSize: 11 }}
    />
  );

  return (
    <div className="flex flex-col" style={{ gap: 16 }}>
      <Flash msg={msg} />
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(380px,1fr))", gap: 18, alignItems: "start" }}>
        {/* sources */}
        <section className="flex flex-col" style={{ gap: 10 }}>
          <span className="eyebrow" style={{ fontSize: 11 }}>Ingestion sources</span>
          {sources === null && <span className="text-mute nipulse" style={{ fontSize: 12 }}>Loading…</span>}
          {sources?.map((s) => (
            <div key={s.id} className="bg-panel border border-line" style={{ borderRadius: "var(--radius)", padding: 14 }}>
              <div className="flex items-center justify-between" style={{ gap: 10 }}>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center" style={{ gap: 8 }}>
                    <span className="text-ink" style={{ fontSize: 12.5, fontWeight: 550 }}>{s.name}</span>
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 600,
                        padding: "2px 8px",
                        borderRadius: 99,
                        color: s.is_active ? "var(--pos)" : "var(--warn)",
                        background: s.is_active ? "var(--possoft)" : "var(--warnsoft)",
                      }}
                    >
                      {s.is_active ? "Active" : "Paused"}
                    </span>
                  </div>
                  <div className="flex items-center" style={{ gap: 14, marginTop: 8 }}>
                    <span className="flex items-center" style={{ gap: 6 }}>
                      <span className="eyebrow">Interval</span>
                      {numInput(Math.round(s.poll_interval / 60), (v) => updateInterval(s, v))}
                      <span className="text-mute" style={{ fontSize: 10 }}>min</span>
                    </span>
                    <span className="flex items-center" style={{ gap: 6 }}>
                      <span className="eyebrow">Limit</span>
                      {numInput(s.articles_per_crawl, (v) => updateLimit(s, v))}
                    </span>
                  </div>
                </div>
                <div className="flex" style={{ gap: 6, flex: "none" }}>
                  {s.type === "rss" && (
                    <Btn variant="ghost" onClick={() => openFeeds(s)} style={{ height: 27, fontSize: 11 }}>
                      Feeds
                    </Btn>
                  )}
                  <Btn
                    onClick={() => toggleSource(s)}
                    style={{
                      height: 27,
                      fontSize: 11,
                      minWidth: 66,
                      color: s.is_active ? "var(--warn)" : "var(--pos)",
                    }}
                  >
                    {s.is_active ? "Disable" : "Enable"}
                  </Btn>
                </div>
              </div>
            </div>
          ))}
        </section>

        {/* detail panel: feeds of selected source, else subreddits */}
        <section className="flex flex-col" style={{ gap: 10 }}>
          {selectedSource ? (
            <>
              <div className="flex items-center justify-between">
                <span className="eyebrow" style={{ fontSize: 11 }}>
                  RSS feeds — {selectedSource.name}
                </span>
                <button
                  onClick={() => setSelectedSource(null)}
                  className="text-mute hover:text-ink"
                  style={{ fontSize: 11, background: "transparent", border: "none" }}
                >
                  ✕ close
                </button>
              </div>
              <div
                className="bg-panel border border-line"
                style={{ borderRadius: "var(--radius)", padding: 14, maxHeight: 560, overflowY: "auto" }}
              >
                {!feeds && <span className="text-mute nipulse" style={{ fontSize: 12 }}>Loading feeds…</span>}
                {feeds?.map((f) => (
                  <div
                    key={f.id}
                    className="flex items-center justify-between border-b border-line last:border-0"
                    style={{ padding: "8px 0", gap: 10 }}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="text-ink truncate" style={{ fontSize: 11.5 }}>{f.feed_label}</div>
                      <div className="text-mute font-mono truncate" style={{ fontSize: 9 }}>{f.feed_url}</div>
                    </div>
                    <Btn
                      variant="ghost"
                      onClick={() => toggleFeed(f)}
                      style={{
                        height: 22,
                        fontSize: 9.5,
                        padding: "0 8px",
                        color: f.is_active ? "var(--pos)" : "var(--textmute)",
                        border: `1px solid ${f.is_active ? "var(--posborder)" : "var(--border)"}`,
                      }}
                    >
                      {f.is_active ? "ACTIVE" : "PAUSED"}
                    </Btn>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <>
              <span className="eyebrow" style={{ fontSize: 11 }}>Reddit subreddits</span>
              <div className="bg-panel border border-line" style={{ borderRadius: "var(--radius)", padding: 14 }}>
                <form onSubmit={addSubreddit} className="flex" style={{ gap: 6, marginBottom: 14 }}>
                  <Input
                    placeholder="Subreddit name"
                    value={newSub.name}
                    onChange={(e) => setNewSub({ ...newSub, name: e.target.value })}
                    required
                    style={{ flex: 1, padding: "6px 9px", fontSize: 12 }}
                  />
                  <Input
                    type="number"
                    title="Posts per crawl"
                    value={newSub.limit}
                    onChange={(e) => setNewSub({ ...newSub, limit: e.target.value })}
                    style={{ width: 64, padding: "6px 9px", fontSize: 12 }}
                  />
                  <select
                    value={newSub.sort}
                    onChange={(e) => setNewSub({ ...newSub, sort: e.target.value })}
                    className="bg-bg2 text-ink border border-line2 outline-none"
                    style={{ padding: "6px 8px", borderRadius: "var(--radius)", fontSize: 12 }}
                  >
                    <option value="new">New</option>
                    <option value="hot">Hot</option>
                    <option value="top">Top</option>
                  </select>
                  <Btn type="submit" variant="primary" style={{ height: 32 }}>
                    Add
                  </Btn>
                </form>
                <div className="flex flex-col" style={{ gap: 8, maxHeight: 420, overflowY: "auto" }}>
                  {subreddits === null && (
                    <span className="text-mute nipulse" style={{ fontSize: 12 }}>Loading…</span>
                  )}
                  {subreddits?.map((sub) => (
                    <div
                      key={sub.id}
                      className="flex items-center justify-between bg-bg2 border border-line"
                      style={{ padding: 10, borderRadius: "var(--radiussm)" }}
                    >
                      <div>
                        <div className="text-ink" style={{ fontSize: 12.5, fontWeight: 550 }}>
                          r/{sub.name}
                        </div>
                        <div className="flex" style={{ gap: 12, marginTop: 3 }}>
                          <span className="text-mute font-mono" style={{ fontSize: 9 }}>
                            SORT {sub.sort.toUpperCase()}
                          </span>
                          <span className="text-mute font-mono" style={{ fontSize: 9 }}>
                            LIMIT {sub.limit_per_crawl}
                          </span>
                        </div>
                      </div>
                      <div className="flex items-center" style={{ gap: 6 }}>
                        <Btn
                          variant="ghost"
                          onClick={() => toggleSubreddit(sub)}
                          style={{
                            height: 24,
                            fontSize: 10,
                            padding: "0 9px",
                            color: sub.is_active ? "var(--pos)" : "var(--textmute)",
                          }}
                        >
                          {sub.is_active ? "ON" : "OFF"}
                        </Btn>
                        <button
                          onClick={() => deleteSubreddit(sub.id)}
                          className="grid place-items-center text-mute hover:text-neg transition-colors"
                          style={{ background: "transparent", border: "none", padding: 4 }}
                        >
                          <Trash2 size={13} strokeWidth={1.55} />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
