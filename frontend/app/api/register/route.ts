import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000/v1";

/** Forwards registration to the backend (no session required). */
export async function POST(req: NextRequest) {
  let res: Response;
  try {
    res = await fetch(`${BACKEND_URL}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: await req.text(),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ error: "Backend unreachable" }, { status: 502 });
  }
  const body = await res.text();
  return new NextResponse(body, {
    status: res.status,
    headers: {
      "Content-Type": res.headers.get("content-type") ?? "application/json",
    },
  });
}
