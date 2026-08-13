// Display helpers shared across screens.

/**
 * Master switch for every social-source surface (Reddit posts, analyzed
 * comments and the sentiment derived from them).
 *
 * Reddit revoked access to the API we crawl through, so those surfaces have no
 * data behind them and render "N/A". The UI is left fully in place — just not
 * rendered — so flipping this back to `true` restores it once Reddit access
 * returns or another social source is wired up in its place.
 */
export const SOCIAL_SIGNALS_ENABLED = false;

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

/**
 * Two-unit relative time: "1 day and 3 hours ago", "3 hours and 12 minutes ago".
 *
 * Separate from `timeAgo`, which stays single-unit and compact — it is used in
 * alert cards and admin tables where width is tight. This form is for the
 * discovery timeline, where "3d ago" is too coarse to tell two runs apart:
 * discovery fires every few hours, so several runs collapse onto the same label.
 */
export function timeAgoLong(isoStr?: string | null): string {
  if (!isoStr) return "";
  const diffMs = Date.now() - new Date(isoStr).getTime();
  const totalMins = Math.max(0, Math.floor(diffMs / 60000));
  if (totalMins < 1) return "just now";

  const unit = (n: number, name: string) => `${n} ${name}${n === 1 ? "" : "s"}`;

  const days = Math.floor(totalMins / 1440);
  const hours = Math.floor((totalMins % 1440) / 60);
  const mins = totalMins % 60;

  // Only ever show the two largest non-zero units — "2 days and 4 hours" reads;
  // "2 days, 4 hours and 17 minutes" does not.
  if (days > 0) {
    return hours > 0
      ? `${unit(days, "day")} and ${unit(hours, "hour")} ago`
      : `${unit(days, "day")} ago`;
  }
  if (hours > 0) {
    return mins > 0
      ? `${unit(hours, "hour")} and ${unit(mins, "minute")} ago`
      : `${unit(hours, "hour")} ago`;
  }
  return `${unit(mins, "minute")} ago`;
}

/** Absolute run timestamp, e.g. "14 Aug, 09:42" — pairs with timeAgoLong. */
export function runStamp(isoStr?: string | null): string {
  if (!isoStr) return "";
  const d = new Date(isoStr);
  return d.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
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

/**
 * Signed percentage, or an em dash when there is no baseline.
 *
 * The backend sends null for `new` and `revival` — there is no honest
 * percentage for a narrative that appeared from nothing, and fabricating one is
 * what previously rendered a revived 7-article cluster as "+700%".
 */
export function growthDisplay(growth: number | null | undefined): string {
  if (growth == null) return "—";
  const v = Math.round(growth * 100);
  // Math.round(-0.4) is -0 in JS, and -0 >= 0 is true, so a small decline used
  // to render as "+0%". Object.is distinguishes -0 from 0.
  if (v === 0) return Object.is(v, -0) || growth < 0 ? "-0%" : "+0%";
  return v > 0 ? `+${v}%` : `${v}%`;
}

/**
 * status → chip text. The backend vocabulary is
 * new | growing | steady | declining | dormant | revival | rejected;
 * legacy rows written before the state-machine migration may still carry
 * emerging | active | inactive.
 */
export function statusLabel(status: string): string {
  switch (status) {
    case "new":
    case "emerging":
      return "New";
    case "growing":
      return "Growing";
    case "steady":
    case "active":
      return "Steady";
    case "declining":
      return "Declining";
    case "dormant":
    case "inactive":
      return "Dormant";
    case "revival":
      return "Revival";
    case "rejected":
      return "Rejected";
    default:
      return status.charAt(0).toUpperCase() + status.slice(1);
  }
}

/** Colour for the growth figure, keyed to the state rather than the sign. */
export function growthColor(
  status: string,
  growth: number | null | undefined,
): string {
  if (status === "new") return "var(--accent2)";
  if (status === "revival") return "var(--warn)";
  if (status === "dormant") return "var(--textmute)";
  if (growth == null) return "var(--textmute)";
  if (growth > 0) return "var(--pos)";
  if (growth < 0) return "var(--warn)";
  return "var(--textdim)";
}

/**
 * status → chip colors.
 *
 * The backend vocabulary is new | growing | steady | declining | dormant |
 * revival | rejected. The legacy values (emerging/active/inactive) are kept as
 * aliases so rows written before the state-machine migration still render.
 */
export function statusColors(status: string): { fg: string; bg: string } {
  switch (status) {
    case "new":
    case "emerging": // legacy
      return { fg: "var(--accent2)", bg: "var(--accentsoft)" };
    case "growing":
      return { fg: "var(--pos)", bg: "var(--possoft)" };
    case "revival":
      return { fg: "var(--warn)", bg: "var(--warnsoft)" };
    case "declining":
      return { fg: "var(--warn)", bg: "var(--warnsoft)" };
    case "steady":
    case "active": // legacy
      return { fg: "var(--textdim)", bg: "var(--neusoft)" };
    default: // dormant, rejected, anything unrecognised
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
