import { NextResponse } from "next/server";
import { auth } from "@/auth";

/**
 * Route guard (Next 16 "proxy", formerly middleware).
 *
 * - /login, /register: public; signed-in users are bounced to the feed.
 * - /admin*: guarded by the httpOnly admin_key cookie (set by the admin
 *   sign-in route handler), independent of the user session.
 * - Everything else under the app requires a NextAuth session.
 */
export default auth((req) => {
  const { pathname } = req.nextUrl;
  const isAuthed = !!req.auth;

  if (pathname === "/login" || pathname === "/register") {
    if (isAuthed) {
      return NextResponse.redirect(new URL("/", req.nextUrl));
    }
    return NextResponse.next();
  }

  if (pathname.startsWith("/admin")) {
    const hasAdminKey = !!req.cookies.get("admin_key")?.value;
    if (!hasAdminKey && pathname !== "/admin/login") {
      return NextResponse.redirect(new URL("/admin/login", req.nextUrl));
    }
    if (hasAdminKey && pathname === "/admin/login") {
      return NextResponse.redirect(new URL("/admin", req.nextUrl));
    }
    return NextResponse.next();
  }

  if (!isAuthed) {
    return NextResponse.redirect(new URL("/login", req.nextUrl));
  }
  return NextResponse.next();
});

export const config = {
  // Everything except Next internals, static assets, and API routes
  // (API routes do their own auth — the backend proxy checks the session).
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\.png$).*)"],
};
