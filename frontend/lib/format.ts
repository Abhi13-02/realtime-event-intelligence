// Display helpers shared across screens.

export function timeAgo(isoStr?: string | null): string {
  if (!isoStr) return "";
  const diffMs = Date.now() - new Date(isoStr).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return `${Math.floor(days / 7)}w ago`;
}

export function formatVolume(n: number | null | undefined): string {
  if (n == null) return "0";
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

/** sentiment_score is -1..1 from the backend; display as signed -100..100 */
export function sentimentDisplay(score: number | null | undefined): string {
  if (score == null) return "N/A";
  const v = Math.round(score * 100);
  return v > 0 ? `+${v}` : String(v);
}

/** ≥ +15 positive, ≤ −15 negative, else neutral (handoff thresholds on ±100 scale) */
export function sentimentToken(
  score: number | null | undefined,
): "pos" | "neg" | "neu" {
  if (score == null) return "neu";
  const v = score * 100;
  if (v >= 15) return "pos";
  if (v <= -15) return "neg";
  return "neu";
}

export function sentimentColor(score: number | null | undefined): string {
  const t = sentimentToken(score);
  return t === "pos" ? "var(--pos)" : t === "neg" ? "var(--neg)" : "var(--neu)";
}

export function growthDisplay(growth: number | null | undefined): string {
  if (growth == null) return "—";
  const v = Math.round(growth * 100);
  return v >= 0 ? `+${v}%` : `${v}%`;
}

/** status → chip colors per handoff mapping */
export function statusColors(status: string): { fg: string; bg: string } {
  switch (status) {
    case "emerging":
      return { fg: "var(--accent2)", bg: "var(--accentsoft)" };
    case "growing":
    case "active":
      return { fg: "var(--pos)", bg: "var(--possoft)" };
    case "declining":
      return { fg: "var(--warn)", bg: "var(--warnsoft)" };
    default:
      return { fg: "var(--textmute)", bg: "var(--neusoft)" };
  }
}

/** relevance tier → bar color: ≥90 pos, ≥82 accent, else warn */
export function relevanceColor(pct: number): string {
  if (pct >= 90) return "var(--pos)";
  if (pct >= 82) return "var(--accent)";
  return "var(--warn)";
}

export function initials(name?: string | null): string {
  if (!name) return "?";
  return name
    .split(/\s+/)
    .map((w) => w[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
}
