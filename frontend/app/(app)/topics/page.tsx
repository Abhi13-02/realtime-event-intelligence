"use client";

// Topics dashboard — responsive card grid per handoff, with all old-frontend
// features: create/edit modal, delete, active/paused toggle, sensitivity
// chip, click-through to the deep dive.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { MoreVertical } from "lucide-react";
import TopicModal from "@/components/topic-modal";
import { api } from "@/lib/api";
import type { Topic } from "@/lib/types";

function sensChip(sensitivity: string) {
  const map: Record<string, { fg: string; bg: string }> = {
    broad: { fg: "var(--textmute)", bg: "var(--neusoft)" },
    balanced: { fg: "var(--accent2)", bg: "var(--accentsoft)" },
    high: { fg: "var(--warn)", bg: "var(--warnsoft)" },
  };
  const c = map[sensitivity] ?? map.balanced;
  return (
    <span
      style={{
        fontSize: 10,
        fontWeight: 600,
        color: c.fg,
        background: c.bg,
        padding: "3px 9px",
        borderRadius: 99,
        textTransform: "capitalize",
      }}
    >
      {sensitivity}
    </span>
  );
}

export default function TopicsPage() {
  const router = useRouter();
  const [topics, setTopics] = useState<Topic[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Topic | null>(null);
  const [menuFor, setMenuFor] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const res = await api.getTopics(1, 50);
      setTopics(res.data ?? []);
    } catch {
      setTopics([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (menuFor === null) return;
    const close = () => setMenuFor(null);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [menuFor]);

  const toggleActive = async (e: React.MouseEvent, topic: Topic) => {
    e.stopPropagation();
    const next = !topic.is_active;
    setTopics((prev) =>
      prev.map((t) => (t.id === topic.id ? { ...t, is_active: next } : t)),
    );
    try {
      await api.updateTopic(topic.id, { is_active: next });
    } catch {
      setTopics((prev) =>
        prev.map((t) => (t.id === topic.id ? { ...t, is_active: !next } : t)),
      );
    }
  };

  const remove = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    setMenuFor(null);
    if (!window.confirm("Delete this topic and all its data?")) return;
    setTopics((prev) => prev.filter((t) => t.id !== id));
    try {
      await api.deleteTopic(id);
    } catch {
      load();
    }
  };

  return (
    <div style={{ maxWidth: 1120, margin: "0 auto", padding: "22px 24px 44px" }}>
      <div className="flex items-center justify-between" style={{ marginBottom: 18 }}>
        <div className="text-mute" style={{ fontSize: 12 }}>
          Topics you actively monitor · discovery runs automatically on your
          schedule
        </div>
        <button
          onClick={() => {
            setEditing(null);
            setModalOpen(true);
          }}
          className="flex items-center bg-accent text-accentfg hover:bg-accent2 transition-colors"
          style={{ height: 31, padding: "0 13px", borderRadius: "var(--radius)", border: "none", fontSize: 12.5, fontWeight: 600, gap: 6 }}
        >
          <span style={{ fontSize: 15, lineHeight: 1, marginTop: -1 }}>+</span>
          New topic
        </button>
      </div>

      {loading ? (
        <div
          className="grid"
          style={{ gridTemplateColumns: "repeat(auto-fill,minmax(300px,1fr))", gap: "var(--gap)" }}
        >
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="shimmer" style={{ height: 150, borderRadius: "var(--radius)" }} />
          ))}
        </div>
      ) : topics.length === 0 ? (
        <div className="text-center text-mute" style={{ padding: "80px 20px", fontSize: 13 }}>
          No topics yet — create your first topic to start monitoring.
        </div>
      ) : (
        <div
          className="grid"
          style={{ gridTemplateColumns: "repeat(auto-fill,minmax(300px,1fr))", gap: "var(--gap)" }}
        >
          {topics.map((topic) => (
            <div
              key={topic.id}
              onClick={() => router.push(`/topics/${topic.id}`)}
              className="bg-panel border border-line hover:border-line2 cursor-pointer flex flex-col transition-colors nifade"
              style={{ borderRadius: "var(--radius)", padding: 16, gap: 12 }}
            >
              <div className="flex items-start justify-between" style={{ gap: 10 }}>
                <div className="min-w-0">
                  <div
                    className="text-ink"
                    style={{ fontSize: 14.5, fontWeight: 600, letterSpacing: "-.01em" }}
                  >
                    {topic.name}
                  </div>
                </div>
                <div className="flex items-center" style={{ gap: 6, flex: "none" }}>
                  {sensChip(topic.sensitivity)}
                  <div style={{ position: "relative" }}>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setMenuFor(menuFor === topic.id ? null : topic.id);
                      }}
                      title="Topic options"
                      className="grid place-items-center text-mute hover:text-ink hover:bg-bg2 transition-colors"
                      style={{ width: 24, height: 24, borderRadius: "var(--radiussm)", border: "none", background: "transparent" }}
                    >
                      <MoreVertical size={14} strokeWidth={1.55} />
                    </button>
                    {menuFor === topic.id && (
                      <div
                        style={{
                          position: "absolute",
                          top: 27,
                          right: 0,
                          zIndex: 30,
                          width: 132,
                          background: "var(--panel)",
                          border: "1px solid var(--border2)",
                          borderRadius: "var(--radius)",
                          boxShadow: "var(--shadowlg)",
                          padding: 4,
                          display: "flex",
                          flexDirection: "column",
                          gap: 1,
                        }}
                      >
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setMenuFor(null);
                            setEditing(topic);
                            setModalOpen(true);
                          }}
                          className="text-ink hover:bg-bg2 text-left w-full transition-colors"
                          style={{ padding: "7px 8px", borderRadius: "var(--radiussm)", border: "none", background: "transparent", fontSize: 12, fontWeight: 500 }}
                        >
                          Edit
                        </button>
                        <button
                          onClick={(e) => remove(e, topic.id)}
                          className="text-neg hover:bg-negsoft text-left w-full transition-colors"
                          style={{ padding: "7px 8px", borderRadius: "var(--radiussm)", border: "none", background: "transparent", fontSize: 12, fontWeight: 500 }}
                        >
                          Delete
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              <div className="text-mute" style={{ fontSize: 12, lineHeight: 1.45, minHeight: 34 }}>
                {topic.description || "No description provided."}
              </div>

              <div
                className="flex items-center justify-between border-t border-line"
                style={{ paddingTop: 12 }}
              >
                <button
                  onClick={(e) => toggleActive(e, topic)}
                  className="flex items-center transition-colors"
                  style={{
                    gap: 6,
                    padding: "3px 10px",
                    borderRadius: 99,
                    fontSize: 10,
                    fontWeight: 700,
                    letterSpacing: ".04em",
                    border: `1px solid ${topic.is_active !== false ? "var(--posborder)" : "var(--border)"}`,
                    background: topic.is_active !== false ? "var(--possoft)" : "var(--neusoft)",
                    color: topic.is_active !== false ? "var(--pos)" : "var(--textmute)",
                  }}
                >
                  <span
                    className={topic.is_active !== false ? "nipulse" : ""}
                    style={{
                      width: 5,
                      height: 5,
                      borderRadius: "50%",
                      background: topic.is_active !== false ? "var(--pos)" : "var(--textmute)",
                    }}
                  />
                  {topic.is_active !== false ? "ACTIVE" : "PAUSED"}
                </button>
                <span className="text-mute" style={{ fontSize: 10.5 }}>
                  Open deep dive →
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      <TopicModal
        open={modalOpen}
        onClose={() => {
          setModalOpen(false);
          setEditing(null);
        }}
        onSaved={load}
        topic={editing}
      />
    </div>
  );
}
