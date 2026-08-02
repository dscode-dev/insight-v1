// Edge middleware — Sprint 8.
//
// Runs on EVERY request before any route handler / server component.
// Two responsibilities:
//   1. Stamp a per-request correlation id (`x-request-id`). The BFF
//      forwards it to the admin API; logs across services pivot on it.
//   2. Gate access to console + api routes by presence of the
//      session cookie. Anonymous requests to anything under
//      `/(console)` or `/api/v1` are redirected to /login.
//
// NOTE: we do NOT verify the JWT here. Edge runtime + jose's verify
// would force the JWKS into the Edge bundle. Cookie presence is a
// cheap gate; the JWT is verified inside each server component +
// route handler via `currentOperator()` / `requireOperator()`.

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { SESSION_COOKIE } from "@/lib/session";
import { basePath, withoutBasePath } from "@/lib/base-path";

const PUBLIC_PATHS = new Set([
  "/login",
  "/api/auth/login",
  "/api/auth/logout",
  "/api/health",
  "/favicon.ico",
]);

function isPublic(pathname: string): boolean {
  if (PUBLIC_PATHS.has(pathname)) return true;
  if (pathname.startsWith("/_next")) return true;
  if (pathname.startsWith("/api/auth/")) return true;
  if (pathname.startsWith("/static/")) return true;
  return false;
}

function randomRequestId(): string {
  // ULID-ish: timestamp + 8 random hex. Good enough for log
  // correlation; not a security primitive.
  const ts = Date.now().toString(16);
  const rand = Array.from(
    crypto.getRandomValues(new Uint8Array(8)),
    (b) => b.toString(16).padStart(2, "0"),
  ).join("");
  return `req_${ts}_${rand}`;
}

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const appPathname = withoutBasePath(pathname);
  const requestId = req.headers.get("x-request-id") ?? randomRequestId();

  // Defensive canonicalization: if a stale client/proxy ever requests
  // /console/console/... under NEXT_PUBLIC_BASE_PATH=/console, collapse it to
  // /console/... before the App Router sees a non-existent /console route.
  if (basePath && appPathname.startsWith(`${basePath}/`)) {
    const canonicalUrl = req.nextUrl.clone();
    canonicalUrl.pathname = withoutBasePath(appPathname);
    const res = NextResponse.redirect(canonicalUrl);
    res.headers.set("x-request-id", requestId);
    return res;
  }

  // Public route — let it through, just stamp the id.
  if (isPublic(appPathname)) {
    const res = NextResponse.next();
    res.headers.set("x-request-id", requestId);
    return res;
  }

  const hasSession = req.cookies.has(SESSION_COOKIE);
  if (!hasSession) {
    // API route: return 401 JSON so client code can react cleanly.
    if (appPathname.startsWith("/api/")) {
      return new NextResponse(
        JSON.stringify({ error: "unauthenticated" }),
        {
          status: 401,
          headers: {
            "Content-Type": "application/json",
            "x-request-id": requestId,
          },
        },
      );
    }
    // Console page: redirect to login with the original target.
    const loginUrl = req.nextUrl.clone();
    // nextUrl is basePath-aware: assigning the application pathname lets
    // Next add /console exactly once when serializing the redirect.
    loginUrl.pathname = "/login";
    loginUrl.searchParams.set("next", appPathname);
    return NextResponse.redirect(loginUrl);
  }

  const res = NextResponse.next();
  res.headers.set("x-request-id", requestId);
  return res;
}

export const config = {
  matcher: [
    /*
     * Match everything except:
     *   - _next/static, _next/image (build artefacts)
     *   - any file with an extension (assets)
     */
    "/((?!_next/static|_next/image|.*\\..*).*)",
  ],
};
