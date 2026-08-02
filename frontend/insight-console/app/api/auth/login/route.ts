// POST /api/auth/login.
//
// Console is not an identity provider. It forwards credentials to Gateway,
// stores only the opaque Gateway operator session in an HttpOnly cookie, and
// returns the Gateway-resolved operator.

import { NextResponse } from "next/server";
import { z } from "zod";

import { adminFetch } from "@/lib/admin-api";
import { SESSION_COOKIE, sessionCookieOptions } from "@/lib/session";

const loginSchema = z.object({
  identifier: z.string().min(1, "identifier_required"),
  password: z.string().min(1, "password_required"),
});

export async function POST(req: Request) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid_body" }, { status: 400 });
  }
  const parsed = loginSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.issues[0]?.message ?? "invalid_input" },
      { status: 400 },
    );
  }

  let upstream: Response;
  try {
    upstream = await adminFetch("/v1/operator/auth/login", {
      method: "POST",
      body: parsed.data,
    });
  } catch {
    return NextResponse.json({ error: "auth_unavailable" }, { status: 503 });
  }
  let payload: {
    session_token?: string;
    operator?: unknown;
  };
  try {
    payload = await upstream.json();
  } catch {
    return NextResponse.json({ error: "auth_unavailable" }, { status: 503 });
  }
  if (!upstream.ok) {
    const status = upstream.status === 401 ? 401 : 503;
    const error = upstream.status === 401 ? "invalid_credentials" : "auth_unavailable";
    return NextResponse.json({ error }, { status });
  }
  if (!payload.session_token || !payload.operator) {
    return NextResponse.json({ error: "auth_unavailable" }, { status: 503 });
  }

  const res = NextResponse.json({ operator: payload.operator });
  res.cookies.set(SESSION_COOKIE, payload.session_token, sessionCookieOptions());
  return res;
}
