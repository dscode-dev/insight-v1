// Console session consumer.
//
// Gateway owns operator authentication, sessions, roles and permissions.
// The Console stores only the opaque Gateway operator session token in an
// HttpOnly cookie and resolves the current operator through Gateway.

import { cookies } from "next/headers";

import { adminFetch } from "@/lib/admin-api";
import { basePath } from "@/lib/base-path";
import type { ConsoleOperator, Permission, Role } from "@/types/auth";

export const SESSION_COOKIE = "insight_console_session";
const COOKIE_MAX_AGE_SECONDS = 60 * 60 * 8;

interface GatewayOperatorDTO {
  id: string;
  username?: string;
  email?: string;
  display_name?: string;
  role: Role;
  permissions: Permission[];
}

function toOperator(dto: GatewayOperatorDTO): ConsoleOperator {
  return {
    id: dto.id,
    displayName: dto.display_name ?? dto.username ?? "operator",
    username: dto.username,
    email: dto.email,
    role: dto.role,
    permissions: dto.permissions,
    issuedAt: 0,
    expiresAt: 0,
  };
}

export function readSessionCookie(): string | null {
  return cookies().get(SESSION_COOKIE)?.value ?? null;
}

export async function currentOperator(): Promise<ConsoleOperator | null> {
  const token = readSessionCookie();
  if (!token) return null;
  try {
    const res = await adminFetch("/v1/operator/auth/me", {
      operatorToken: token,
      timeoutMs: 5000,
    });
    if (!res.ok) return null;
    const body = (await res.json()) as { operator?: GatewayOperatorDTO };
    if (!body.operator) return null;
    return toOperator(body.operator);
  } catch {
    return null;
  }
}

export function sessionCookieOptions() {
  const secure =
    process.env.COOKIE_SECURE !== undefined
      ? process.env.COOKIE_SECURE === "true"
      : process.env.NODE_ENV === "production";
  return {
    httpOnly: true,
    secure,
    sameSite: "lax" as const,
    path: basePath || "/",
    maxAge: COOKIE_MAX_AGE_SECONDS,
  };
}
