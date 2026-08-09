// Console session consumer.
//
// The INSIGHT CONTROL PLANE owns operator authentication, sessions,
// roles and permissions (insight-context.md v2.0). The Console stores
// only the opaque session token in an HttpOnly cookie and resolves the
// current operator through the Control Plane.
//
// This used to resolve against the Insight Gateway, which the
// architecture explicitly excludes from "Administração, Operadores,
// Console, Auditoria administrativa" — it put administrative identity
// in the Product Plane and made the Intelligence plane unable to
// authenticate anyone without reaching the public internet.

import { controlPlaneFetch } from "@/lib/control-plane/adapters/console-api";
import { basePath } from "@/lib/base-path";
import { SESSION_COOKIE, readSessionCookie } from "@/lib/session-cookie";

export { SESSION_COOKIE, readSessionCookie };
import type { ConsoleOperator, Permission, Role } from "@/types/auth";

const COOKIE_MAX_AGE_SECONDS = 60 * 60 * 8;

interface OperatorDTO {
  id: string;
  username?: string;
  email?: string;
  display_name?: string;
  role: Role;
  permissions: Permission[];
}

function toOperator(dto: OperatorDTO): ConsoleOperator {
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

export async function currentOperator(): Promise<ConsoleOperator | null> {
  const token = readSessionCookie();
  if (!token) return null;
  try {
    const res = await controlPlaneFetch("/v1/operator/auth/me", {
      token,
      timeoutMs: 5000,
    });
    if (!res.ok) return null;
    const body = (await res.json()) as { operator?: OperatorDTO };
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
