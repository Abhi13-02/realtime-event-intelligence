import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000/v1";

const COOKIE_OPTS = {
  httpOnly: true,
  sameSite: "lax" as const,
  secure: process.env.NODE_ENV === "production",
  path: "/",
  maxAge: 12 * 60 * 60, // 12h admin session
};

/**
 * POST — admin sign-in. Validates the key against the backend (a cheap
 * authenticated admin call) and stores it in an httpOnly cookie so it never
 * touches client JavaScript. DELETE — sign-out.
 */
export async function POST(req: NextRequest) {
  const { key } = (await req.json().catch(() => ({}))) as { key?: string };
  if (!key?.trim()) {
    return NextResponse.json({ error: "Key required" }, { status: 400 });
  }

  let check: Response;
  try {
    check = await fetch(`${BACKEND_URL}/admin/users`, {
      headers: { "X-Admin-Key": key.trim() },
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ error: "Backend unreachable" }, { status: 502 });
  }
  if (check.status === 401) {
    return NextResponse.json({ error: "Invalid admin key" }, { status: 401 });
  }
  if (!check.ok) {
    return NextResponse.json({ error: "Validation failed" }, { status: 502 });
  }

  const res = NextResponse.json({ ok: true });
  res.cookies.set("admin_key", key.trim(), COOKIE_OPTS);
  return res;
}

export async function DELETE() {
  const res = NextResponse.json({ ok: true });
  res.cookies.set("admin_key", "", { ...COOKIE_OPTS, maxAge: 0 });
  res.cookies.set("impersonate_user_id", "", { ...COOKIE_OPTS, httpOnly: false, maxAge: 0 });
  return res;
}
