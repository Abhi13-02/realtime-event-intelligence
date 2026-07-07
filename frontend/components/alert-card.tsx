"use client";

// Alert card per handoff feed spec, carrying every old-frontend feature:
// real article image (striped placeholder when missing), source + topic
// chips, relevance bar with tier color, dismiss, open-article link, and —
// for Reddit posts — an expandable list of analyzed comments with
// sentiment + score.

import { useState } from "react";
import { ChevronDown, X } from "lucide-react";
import { api } from "@/lib/api";
import type { Alert, RedditComment } from "@/lib/types";
import {
  relevanceColor,
  sentimentColor,
  sentimentToken,
  timeAgo,
} from "@/lib/format";

export default function AlertCard({
  alert,
  onDismiss,
  onOpen,
  hideTopicTag = false,
}: {
  alert: Alert;
  onDismiss?: (id: string) => void;
  onOpen?: () => void;
  hideTopicTag?: boolean;
}) {
  const [showComments, setShowComments] = useState(false);
  const [comments, setComments] = useState<RedditComment[] | null>(null);
  const [loadingComments, setLoadingComments] = useState(false);

  const isReddit =
    alert.membership_type === "reddit" ||
    alert.source_name?.toUpperCase().includes("REDDIT");
  const relPct =
    alert.relevance_score != null
      ? Math.round(
          (alert.similarity_to_centroid ?? alert.relevance_score) * 100,
        )
      : null;
  const timestamp = alert.created_at ?? alert.published_at;

  const toggleComments = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!showComments && comments === null) {
      setLoadingComments(true);
      try {
        const res = await api.getArticleComments(alert.article_id ?? alert.id);
        setComments(res.comments ?? []);
      } catch {
        setComments([]);
      } finally {
        setLoadingComments(false);
      }
    }
    setShowComments(!showComments);
  };

  return (
    <div
      onClick={onOpen}
      className={`bg-panel border border-line nifade transition-colors ${onOpen ? "cursor-pointer hover:bg-panel2 hover:border-line2" : "hover:border-line2"}`}
      style={{ borderRadius: "var(--radius)", padding: 14 }}
    >
      <div className="flex" style={{ gap: 14 }}>
        {alert.image_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={alert.image_url}
            alt=""
            className="object-cover"
            style={{
              width: 100,
              height: 85,
              flex: "none",
              borderRadius: "var(--radiussm)",
              border: "1px solid var(--border)",
            }}
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = "none";
            }}
          />
        ) : (
          <div
            className="thumb-stripes grid place-items-center"
            style={{ width: 62, height: 62, flex: "none", borderRadius: "var(--radiussm)" }}
          >
            <span className="font-mono text-mute" style={{ fontSize: 8.5, letterSpacing: ".05em" }}>
              IMG
            </span>
          </div>
        )}

        <div className="flex-1 min-w-0">
          <div className="flex items-center flex-wrap" style={{ gap: 8, marginBottom: 6 }}>
            <span
              style={{
                fontSize: 10,
                fontWeight: 600,
                padding: "2px 8px",
                borderRadius: 99,
                color: isReddit ? "var(--warn)" : "var(--accent2)",
                background: isReddit ? "var(--warnsoft)" : "var(--accentsoft)",
              }}
            >
              {alert.source_name || "News"}
            </span>
            {alert.topic_name && !hideTopicTag && (
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 600,
                  padding: "2px 8px",
                  borderRadius: 99,
                  color: "var(--pos)",
                  background: "var(--possoft)",
                }}
              >
                {alert.topic_name}
              </span>
            )}
            {timestamp && (
              <>
                <span style={{ width: 3, height: 3, borderRadius: "50%", background: "var(--textmute)" }} />
                <span className="text-mute" style={{ fontSize: 11 }}>
                  {timeAgo(timestamp)}
                </span>
              </>
            )}
          </div>

          <div
            className="text-ink"
            style={{ fontSize: 14, fontWeight: 550, lineHeight: 1.35, letterSpacing: "-.01em", marginBottom: alert.summary ? 6 : 11 }}
          >
            {alert.headline}
          </div>
          {alert.summary && (
            <div
              className="text-mute"
              style={{
                fontSize: 12,
                lineHeight: 1.45,
                marginBottom: 11,
                display: "-webkit-box",
                WebkitLineClamp: 2,
                WebkitBoxOrient: "vertical",
                overflow: "hidden",
              }}
            >
              {alert.summary}
            </div>
          )}

          <div className="flex items-center" style={{ gap: 10 }}>
            {relPct != null && (
              <div className="flex items-center" style={{ gap: 10, maxWidth: 280, flex: 1 }}>
                <span className="eyebrow">Relevance</span>
                <div
                  className="flex-1"
                  style={{ height: 4, borderRadius: 99, background: "var(--panel2)", overflow: "hidden" }}
                >
                  <div
                    style={{
                      width: `${relPct}%`,
                      height: "100%",
                      borderRadius: 99,
                      background: relevanceColor(relPct),
                    }}
                  />
                </div>
                <span style={{ fontSize: 11.5, fontWeight: 600, color: relevanceColor(relPct) }}>
                  {relPct}%
                </span>
              </div>
            )}
            <div className="flex-1" />
            <a
              href={alert.url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="text-mute hover:text-accent2 transition-colors"
              style={{ fontSize: 11, fontWeight: 550 }}
            >
              {isReddit ? "View post ↗" : "Read article ↗"}
            </a>
            {isReddit && (
              <button
                onClick={toggleComments}
                className={`flex items-center transition-colors ${showComments ? "text-accent2" : "text-mute hover:text-ink"}`}
                style={{ gap: 4, fontSize: 11, fontWeight: 550, background: "transparent", border: "none", padding: 0 }}
              >
                {loadingComments ? "Loading…" : "Comments"}
                <ChevronDown
                  size={12}
                  strokeWidth={1.55}
                  style={{ transform: showComments ? "rotate(180deg)" : "none", transition: "transform .15s" }}
                />
              </button>
            )}
          </div>
        </div>

        {onDismiss && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDismiss(alert.id);
            }}
            title="Dismiss"
            className="grid place-items-center text-mute hover:text-ink hover:bg-bg2 transition-colors self-start"
            style={{
              width: 26,
              height: 26,
              flex: "none",
              borderRadius: "var(--radiussm)",
              border: "1px solid transparent",
              background: "transparent",
            }}
          >
            <X size={14} strokeWidth={1.55} />
          </button>
        )}
      </div>

      {showComments && isReddit && (
        <div
          className="border-t border-line nifade"
          style={{ marginTop: 12, paddingTop: 12, maxHeight: 256, overflowY: "auto", display: "flex", flexDirection: "column", gap: 8 }}
        >
          {comments !== null && comments.length === 0 && !loadingComments ? (
            <span className="text-mute" style={{ fontSize: 11.5, fontStyle: "italic" }}>
              No analyzed comments found for this post.
            </span>
          ) : (
            comments?.map((c) => (
              <div
                key={c.id}
                className="bg-bg2 border border-line"
                style={{ padding: 11, borderRadius: "var(--radiussm)" }}
              >
                <div className="flex items-start justify-between" style={{ gap: 8, marginBottom: 4 }}>
                  <span className="text-ink" style={{ fontSize: 12.5, lineHeight: 1.45 }}>
                    {c.body}
                  </span>
                  <div className="flex flex-col items-end" style={{ flex: "none" }}>
                    <span style={{ fontSize: 10, fontWeight: 700, color: sentimentColor(c.sentiment_score) }}>
                      {sentimentToken(c.sentiment_score) === "pos"
                        ? "POSITIVE"
                        : sentimentToken(c.sentiment_score) === "neg"
                          ? "NEGATIVE"
                          : "NEUTRAL"}
                    </span>
                    <span className="text-mute font-mono" style={{ fontSize: 9.5 }}>
                      score {c.score}
                    </span>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
