// POST /api/auth/logout.
//
// Clears the session cookie and asks the Control Plane to revoke the
// operator session. Both halves matter: dropping only the cookie would
// leave a live session token that anyone holding it could still use.

import { NextResponse } from "next/server";

import { controlPlaneFetch } from "@/lib/control-plane/adapters/console-api";
import { readSessionCookie, SESSION_COOKIE, sessionCookieOptions } from "@/lib/session";

export async function POST() {
  const token = readSessionCookie();
  if (token) {
    try {
      await controlPlaneFetch("/v1/operator/auth/logout", {
        method: "POST",
        token,
      });
    } catch {
      // Cookie cleanup must still happen if the Control Plane is
      // unreachable — otherwise a failed logout leaves the operator
      // apparently signed in.
    }
  }
  const res = NextResponse.json({ status: "logged_out" });
  res.cookies.set(SESSION_COOKIE, "", {
    ...sessionCookieOptions(),
    maxAge: 0,
  });
  return res;
}
