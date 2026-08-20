// Public read-only feed for the landing page.
//
// The page renders this server-side on first paint; the wire re-polls this
// route so a visitor who leaves the tab open keeps seeing current articles.
// All the work — and the demo credentials — live in lib/landing-data.

import { NextResponse } from "next/server";
import { getLandingFeed } from "@/lib/landing-data";

export const dynamic = "force-dynamic";

export async function GET() {
  const feed = await getLandingFeed();
  return NextResponse.json(feed, {
    // getLandingFeed does its own short-lived memoisation; no CDN copy on top,
    // or the "live" claim stops being true.
    headers: { "Cache-Control": "no-store" },
  });
}
