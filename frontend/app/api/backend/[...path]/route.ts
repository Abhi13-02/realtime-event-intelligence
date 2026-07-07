import { NextRequest, NextResponse } from "next/server";
import { decode } from "next-auth/jwt";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000/v1";

/**
 * Server-side proxy for all user-facing backend calls.
 *
 * Keeps credentials out of client JavaScript entirely:
 * - normal session → forwards Authorization: Bearer <backend JWT>
 * - impersonation active (admin_key httpOnly cookie + impersonate_user_id
 *   cookie) → forwards X-Admin-Key + X-As-User-Id instead, exactly like the
 *   backend admin bypass expects.
 */
async function forward(req: NextRequest, path: string[]) {
  const adminKey = req.cookies.get("admin_key")?.value;
  const impersonateId = req.cookies.get("impersonate_user_id")?.value;

  const headers: Record<string, string> = {};
  const contentType = req.headers.get("content-type");
  if (contentType) headers["Content-Type"] = contentType;

  if (adminKey && impersonateId) {
    headers["X-Admin-Key"] = adminKey;
    headers["X-As-User-Id"] = impersonateId;
  } else {
    // Decode the NextAuth session JWT directly. The cookie name depends on
    // whether the browser-facing origin is HTTPS (__Secure- prefix), so try
    // both — v5 salts the encryption with the cookie name.
    const cookieName = req.cookies.has("__Secure-authjs.session-token")
      ? "__Secure-authjs.session-token"
      : "authjs.session-token";
    const raw = req.cookies.get(cookieName)?.value;
    let accessToken: string | undefined;
    if (raw) {
      try {
        const token = await decode({
          token: raw,
          secret: process.env.AUTH_SECRET!,
          salt: cookieName,
        });
        accessToken = token?.accessToken as string | undefined;
      } catch {
        // invalid/expired session token
      }
    }
    if (!accessToken) {
      return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
    }
    headers["Authorization"] = `Bearer ${accessToken}`;
  }

  const url = new URL(`${BACKEND_URL}/${path.join("/")}`);
  req.nextUrl.searchParams.forEach((v, k) => url.searchParams.append(k, v));

  const init: RequestInit = { method: req.method, headers, cache: "no-store" };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.text();
  }

  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    return NextResponse.json(
      { error: "Backend unreachable" },
      { status: 502 },
    );
  }

  const body = await res.text();
  return new NextResponse(body, {
    status: res.status,
    headers: {
      "Content-Type": res.headers.get("content-type") ?? "application/json",
    },
  });
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, ctx: Ctx) {
  return forward(req, (await ctx.params).path);
}
export async function POST(req: NextRequest, ctx: Ctx) {
  return forward(req, (await ctx.params).path);
}
export async function PUT(req: NextRequest, ctx: Ctx) {
  return forward(req, (await ctx.params).path);
}
export async function PATCH(req: NextRequest, ctx: Ctx) {
  return forward(req, (await ctx.params).path);
}
export async function DELETE(req: NextRequest, ctx: Ctx) {
  return forward(req, (await ctx.params).path);
}
