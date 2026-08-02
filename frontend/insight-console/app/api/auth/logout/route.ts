// POST /api/auth/logout — Sprint 8.
//
// Clears the session cookie and asks Gateway to revoke the operator session.

import { NextResponse } from "next/server";

import { adminFetch } from "@/lib/admin-api";
import { readSessionCookie, SESSION_COOKIE, sessionCookieOptions } from "@/lib/session";

export async function POST() {
  const token = readSessionCookie();
  if (token) {
    try {
      await adminFetch("/v1/operator/auth/logout", {
        method: "POST",
        operatorToken: token,
      });
    } catch {
      // Local cookie cleanup must still happen if Gateway is unreachable.
    }
  }
  const res = NextResponse.json({ status: "logged_out" });
  res.cookies.set(SESSION_COOKIE, "", {
    ...sessionCookieOptions(),
    maxAge: 0,
  });
  return res;
}
