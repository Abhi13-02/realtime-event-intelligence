import { NextRequest, NextResponse } from "next/server";

/**
 * Start/stop impersonation. Requires an active admin session (httpOnly
 * admin_key cookie). The impersonate_user_id cookie is deliberately
 * readable by the client so the app shell can show the warning banner —
 * it is only a UUID; the secret key stays httpOnly.
 */
export async function POST(req: NextRequest) {
  if (!req.cookies.get("admin_key")?.value) {
    return NextResponse.json({ error: "Admin session required" }, { status: 401 });
  }
  const { userId } = (await req.json().catch(() => ({}))) as { userId?: string };
  if (!userId) {
    return NextResponse.json({ error: "userId required" }, { status: 400 });
  }
  const res = NextResponse.json({ ok: true });
  res.cookies.set("impersonate_user_id", userId, {
    httpOnly: false,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 12 * 60 * 60,
  });
  return res;
}

export async function DELETE() {
  const res = NextResponse.json({ ok: true });
  res.cookies.set("impersonate_user_id", "", { path: "/", maxAge: 0 });
  return res;
}
