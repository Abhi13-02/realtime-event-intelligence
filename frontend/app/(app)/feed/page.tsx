"use client";

// Home Feed — reverse-chron alert stream. Real data: paginated GET /alerts,
// live WebSocket injection on page 1, dismiss = DELETE /alerts/{id}.
// Handoff states: loading skeletons, empty "all caught up", refresh.

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Inbox } from "lucide-react";
import AlertCard from "@/components/alert-card";
import { Pager, SkeletonRows } from "@/components/ui";
import { api } from "@/lib/api";
import { useWebSocket } from "@/lib/websocket";
import type { Alert } from "@/lib/types";

const PAGE_SIZE = 20;

export default function HomeFeedPage() {
  const router = useRouter();
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const { latestAlert } = useWebSocket();

  const load = useCallback(async (p: number) => {
    setLoading(true);
    try {
      const res = await api.getAlerts(p, PAGE_SIZE);
      setAlerts(res.data ?? []);
      setTotalCount(res.total_count ?? 0);
    } catch {
      setAlerts([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(page);
  }, [page, load]);

  // Live alerts land at the top of page 1 only.
  useEffect(() => {
    if (latestAlert && page === 1) {
      setAlerts((prev) =>
        prev.some((a) => a.id === latestAlert.id) ? prev : [latestAlert, ...prev],
      );
      setTotalCount((c) => c + 1);
    }
  }, [latestAlert, page]);

  const dismiss = async (id: string) => {
    setAlerts((prev) => prev.filter((a) => a.id !== id));
    setTotalCount((c) => Math.max(0, c - 1));
    try {
      await api.deleteAlert(id);
    } catch {
      // optimistic removal; next refresh reconciles
    }
  };

  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));

  return (
    <div style={{ maxWidth: 940, margin: "0 auto", padding: "22px 24px 44px" }}>
      <div className="flex items-center justify-between" style={{ marginBottom: 16 }}>
        <div className="text-mute" style={{ fontSize: 12 }}>
          Real-time alerts across tracked topics ·{" "}
          <span>{totalCount} active</span>
        </div>
        <button
          onClick={() => load(page)}
          className="flex items-center bg-bg2 border border-line2 text-dim hover:text-ink transition-colors"
          style={{ height: 29, padding: "0 12px", borderRadius: "var(--radius)", gap: 7, fontSize: 12, fontWeight: 550 }}
        >
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--pos)" }} />
          Refresh
        </button>
      </div>

      {loading ? (
        <SkeletonRows count={4} />
      ) : alerts.length === 0 ? (
        <div className="flex flex-col items-center justify-center text-center" style={{ padding: "80px 20px" }}>
          <div
            className="grid place-items-center bg-panel border border-line text-mute"
            style={{ width: 52, height: 52, borderRadius: 14, marginBottom: 16 }}
          >
            <Inbox size={20} strokeWidth={1.55} />
          </div>
          <div className="text-ink" style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>
            You&apos;re all caught up
          </div>
          <div className="text-mute" style={{ fontSize: 12.5, maxWidth: 320, lineHeight: 1.5, marginBottom: 18 }}>
            Every alert has been reviewed. New signals will surface here the
            moment they cross your relevance threshold.
          </div>
          <button
            onClick={() => load(1)}
            className="bg-accent text-accentfg hover:bg-accent2 transition-colors"
            style={{ height: 32, padding: "0 15px", borderRadius: "var(--radius)", border: "none", fontSize: 12.5, fontWeight: 600 }}
          >
            Check for new alerts
          </button>
        </div>
      ) : (
        <>
          <div className="flex flex-col" style={{ gap: "var(--gap)" }}>
            {alerts.map((alert) => (
              <AlertCard
                key={alert.id}
                alert={alert}
                onDismiss={dismiss}
                onOpen={
                  alert.topic_id
                    ? () => router.push(`/topics/${alert.topic_id}`)
                    : undefined
                }
              />
            ))}
          </div>
          {totalPages > 1 && (
            <Pager
              page={page}
              totalPages={totalPages}
              onPrev={() => setPage((p) => Math.max(1, p - 1))}
              onNext={() => setPage((p) => Math.min(totalPages, p + 1))}
            />
          )}
        </>
      )}
    </div>
  );
}
