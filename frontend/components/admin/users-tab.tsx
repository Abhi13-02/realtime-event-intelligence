"use client";

// Admin › Users — full parity with the old AdminPanel Users tab:
// load users, delete user (cascading), expand a user's topics, trigger
// discovery per topic, impersonate (assume identity), inspect and delete
// that topic's sub-themes (one or all).

import { useState } from "react";
import { Trash2 } from "lucide-react";
import { Btn, Flash, StatusChip } from "@/components/ui";
import { adminApi } from "@/lib/api";
import type { AdminSubTheme, AdminTopic, AdminUser } from "@/lib/types";
import { initials } from "@/lib/format";

type FlashMsg = { text: string; type: "ok" | "err" } | null;

export default function UsersTab() {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedUser, setSelectedUser] = useState<AdminUser | null>(null);
  const [topics, setTopics] = useState<AdminTopic[] | null>(null);
  const [topicsLoading, setTopicsLoading] = useState(false);
  const [selectedTopic, setSelectedTopic] = useState<AdminTopic | null>(null);
  const [subthemes, setSubthemes] = useState<AdminSubTheme[] | null>(null);
  const [stLoading, setStLoading] = useState(false);
  const [discoveringId, setDiscoveringId] = useState<string | null>(null);
  const [msg, setMsg] = useState<FlashMsg>(null);

  const flash = (text: string, type: "ok" | "err" = "ok") => {
    setMsg({ text, type });
    setTimeout(() => setMsg(null), 4000);
  };

  const loadUsers = async () => {
    setLoading(true);
    try {
      const d = await adminApi.getUsers();
      setUsers(d.users);
    } catch {
      flash("Failed to load users", "err");
    } finally {
      setLoading(false);
    }
  };

  const selectUser = async (user: AdminUser) => {
    setSelectedUser(user);
    setTopics(null);
    setSelectedTopic(null);
    setSubthemes(null);
    setTopicsLoading(true);
    try {
      setTopics(await adminApi.getUserTopics(user.id));
    } catch {
      flash("Failed to load topics", "err");
    } finally {
      setTopicsLoading(false);
    }
  };

  const deleteUser = async (e: React.MouseEvent, userId: string) => {
    e.stopPropagation();
    if (
      !window.confirm(
        "CRITICAL: Delete this user and ALL their data (topics, alerts, sub-themes)? This cannot be undone.",
      )
    )
      return;
    try {
      await adminApi.deleteUser(userId);
      setUsers((prev) => prev?.filter((u) => u.id !== userId) ?? null);
      if (selectedUser?.id === userId) {
        setSelectedUser(null);
        setTopics(null);
      }
      flash("User and all data deleted.");
    } catch {
      flash("Delete failed", "err");
    }
  };

  const selectTopic = async (topic: AdminTopic) => {
    if (selectedTopic?.id === topic.id) {
      setSelectedTopic(null);
      setSubthemes(null);
      return;
    }
    setSelectedTopic(topic);
    setSubthemes(null);
    setStLoading(true);
    try {
      setSubthemes(await adminApi.getTopicSubthemes(selectedUser!.id, topic.id));
    } catch {
      flash("Failed to load sub-themes", "err");
    } finally {
      setStLoading(false);
    }
  };

  const runDiscover = async (topic: AdminTopic) => {
    setDiscoveringId(topic.id);
    try {
      await adminApi.discoverTopic(selectedUser!.id, topic.id);
      flash(`Discovery queued for "${topic.name}"`);
    } catch {
      flash("Discovery failed", "err");
    } finally {
      setDiscoveringId(null);
    }
  };

  const deleteSubtheme = async (id: string) => {
    if (!window.confirm("Delete this sub-theme?")) return;
    try {
      await adminApi.deleteSubtheme(id);
      setSubthemes((prev) => prev?.filter((s) => s.id !== id) ?? null);
      flash("Sub-theme deleted.");
    } catch {
      flash("Delete failed", "err");
    }
  };

  const deleteAllSubthemes = async () => {
    if (!window.confirm(`Delete ALL sub-themes for "${selectedTopic!.name}"?`)) return;
    try {
      await adminApi.deleteTopicSubthemes(selectedUser!.id, selectedTopic!.id);
      setSubthemes([]);
      flash("All sub-themes for topic deleted.");
    } catch {
      flash("Delete failed", "err");
    }
  };

  const impersonate = async (userId: string, topicId?: string) => {
    try {
      await adminApi.impersonate(userId);
      window.location.href = topicId ? `/topics/${topicId}` : "/";
    } catch {
      flash("Impersonation failed", "err");
    }
  };

  return (
    <div className="flex flex-col" style={{ gap: 16 }}>
      <Flash msg={msg} />

      <div className="flex items-center justify-between">
        <span className="eyebrow" style={{ fontSize: 11 }}>All users</span>
        <Btn onClick={loadUsers} disabled={loading}>
          {loading ? "Loading…" : "Load users"}
        </Btn>
      </div>

      {users === null ? (
        <div
          className="text-center text-mute bg-panel border border-line"
          style={{ padding: "40px 12px", borderRadius: "var(--radius)", fontSize: 12 }}
        >
          Click “Load users” to fetch all registered users.
        </div>
      ) : (
        <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(300px,1fr))", gap: "var(--gap)" }}>
          {users.map((u) => (
            <div
              key={u.id}
              onClick={() => selectUser(u)}
              className="cursor-pointer transition-colors group"
              style={{
                padding: 14,
                borderRadius: "var(--radius)",
                border: `1px solid ${selectedUser?.id === u.id ? "var(--accent)" : "var(--border)"}`,
                background: selectedUser?.id === u.id ? "var(--accentsoft)" : "var(--panel)",
              }}
            >
              <div className="flex items-start justify-between" style={{ gap: 8 }}>
                <div className="flex items-center min-w-0" style={{ gap: 9 }}>
                  <div
                    className="grid place-items-center bg-panel2 border border-line2 text-dim"
                    style={{ width: 28, height: 28, borderRadius: 7, fontSize: 10, fontWeight: 600, flex: "none" }}
                  >
                    {initials(u.name)}
                  </div>
                  <div className="min-w-0">
                    <div className="text-ink truncate" style={{ fontSize: 12.5, fontWeight: 550 }}>
                      {u.name}
                    </div>
                    <div className="text-mute truncate" style={{ fontSize: 10.5 }}>
                      {u.email}
                    </div>
                  </div>
                </div>
                <div className="flex items-center" style={{ gap: 6, flex: "none" }}>
                  <span
                    style={{ fontSize: 10, fontWeight: 600, color: "var(--accent2)", background: "var(--accentsoft)", padding: "2px 8px", borderRadius: 99 }}
                  >
                    {u.topic_count} topics
                  </span>
                  <button
                    onClick={(e) => deleteUser(e, u.id)}
                    title="Delete user"
                    className="grid place-items-center text-mute hover:text-neg hover:bg-negsoft transition-colors opacity-0 group-hover:opacity-100"
                    style={{ width: 24, height: 24, borderRadius: "var(--radiussm)", border: "none", background: "transparent" }}
                  >
                    <Trash2 size={13} strokeWidth={1.55} />
                  </button>
                </div>
              </div>
              <div className="text-mute font-mono truncate" style={{ fontSize: 9.5, marginTop: 8 }}>
                {u.id}
              </div>
            </div>
          ))}
        </div>
      )}

      {selectedUser && (
        <div className="bg-panel border border-line" style={{ borderRadius: "var(--radius)", padding: 18 }}>
          <div className="flex items-center justify-between" style={{ marginBottom: 10 }}>
            <div className="flex items-center" style={{ gap: 12 }}>
              <span className="text-ink" style={{ fontSize: 12.5, fontWeight: 600 }}>
                Topics — {selectedUser.name}
              </span>
              <Btn variant="ghost" onClick={() => impersonate(selectedUser.id)} style={{ height: 26, fontSize: 11.5 }}>
                Assume identity →
              </Btn>
            </div>
            <button
              onClick={() => {
                setSelectedUser(null);
                setTopics(null);
                setSelectedTopic(null);
              }}
              className="text-mute hover:text-ink"
              style={{ fontSize: 11, background: "transparent", border: "none" }}
            >
              ✕ close
            </button>
          </div>

          {topicsLoading && (
            <div className="text-mute nipulse" style={{ fontSize: 12 }}>Loading topics…</div>
          )}
          {topics?.length === 0 && (
            <div className="text-mute" style={{ fontSize: 12, fontStyle: "italic" }}>No topics.</div>
          )}
          {topics?.map((t) => (
            <div key={t.id} className="border-b border-line last:border-0" style={{ padding: "10px 0" }}>
              <div className="flex items-center justify-between" style={{ gap: 10 }}>
                <button
                  onClick={() => selectTopic(t)}
                  className="flex-1 text-left min-w-0 hover:text-accent2 transition-colors"
                  style={{ background: "transparent", border: "none", padding: 0 }}
                >
                  <div
                    style={{ fontSize: 12.5, fontWeight: 550, color: selectedTopic?.id === t.id ? "var(--accent2)" : "var(--text)" }}
                  >
                    {selectedTopic?.id === t.id ? "▾" : "▸"} {t.name}
                  </div>
                  <div className="text-mute font-mono" style={{ fontSize: 9.5, paddingLeft: 14 }}>
                    {t.id}
                  </div>
                </button>
                <div className="flex items-center" style={{ gap: 6, flex: "none" }}>
                  <span
                    style={{ fontSize: 10, fontWeight: 600, color: "var(--warn)", background: "var(--warnsoft)", padding: "2px 8px", borderRadius: 99, textTransform: "capitalize" }}
                  >
                    {t.sensitivity}
                  </span>
                  <Btn
                    onClick={() => runDiscover(t)}
                    disabled={discoveringId === t.id}
                    style={{ height: 26, fontSize: 11 }}
                  >
                    {discoveringId === t.id ? "Queuing…" : "Discover"}
                  </Btn>
                  <Btn
                    variant="ghost"
                    onClick={() => impersonate(selectedUser.id, t.id)}
                    style={{ height: 26, fontSize: 11 }}
                  >
                    Intel ↗
                  </Btn>
                </div>
              </div>

              {selectedTopic?.id === t.id && (
                <div
                  className="border-l border-line"
                  style={{ marginLeft: 4, marginTop: 8, paddingLeft: 14, display: "flex", flexDirection: "column", gap: 8 }}
                >
                  <div className="flex items-center justify-between">
                    <span className="eyebrow">Discovered sub-themes</span>
                    {subthemes && subthemes.length > 0 && (
                      <button
                        onClick={deleteAllSubthemes}
                        className="text-neg hover:opacity-80"
                        style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", background: "transparent", border: "none" }}
                      >
                        Wipe all for topic
                      </button>
                    )}
                  </div>
                  {stLoading && (
                    <span className="text-mute nipulse" style={{ fontSize: 11 }}>Fetching sub-themes…</span>
                  )}
                  {subthemes?.length === 0 && (
                    <span className="text-mute" style={{ fontSize: 11, fontStyle: "italic" }}>
                      No sub-themes discovered yet.
                    </span>
                  )}
                  {subthemes?.map((st) => (
                    <div
                      key={st.id}
                      className="flex items-center justify-between bg-bg2 border border-line"
                      style={{ padding: 8, borderRadius: "var(--radiussm)" }}
                    >
                      <div className="min-w-0">
                        <div className="text-ink truncate" style={{ fontSize: 12 }}>{st.label}</div>
                        <div className="flex items-center" style={{ gap: 8, marginTop: 3 }}>
                          <StatusChip status={st.status} />
                          <span className="text-mute font-mono" style={{ fontSize: 9.5 }}>
                            {st.total_volume ?? 0} vol
                          </span>
                        </div>
                      </div>
                      <button
                        onClick={() => deleteSubtheme(st.id)}
                        className="text-mute hover:text-neg transition-colors"
                        style={{ fontSize: 10.5, fontWeight: 600, textTransform: "uppercase", background: "transparent", border: "none", flex: "none" }}
                      >
                        Delete
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
