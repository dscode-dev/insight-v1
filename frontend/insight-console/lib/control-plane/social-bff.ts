// Social BFF helper (CONSOLE-SOCIAL-A1). SERVER-ONLY.
//
// Every Social read route: resolve OperatorContext (verified session) → authorize
// the capability (real decision; registry presence never grants) → call the typed
// Social adapter → map canonical control-plane errors to structured responses.
// The browser never talks to Social; no service token is exposed.

import { ConsoleApiError } from "@/lib/admin-api";
import { withApiHandler } from "@/lib/api-guard";
import { readSessionCookie } from "@/lib/session";
import { resolveOperatorContext } from "@/lib/control-plane/security/operator-context";
import { authorize } from "@/lib/control-plane/security/authorization";
import { observeSecurity } from "@/lib/control-plane/security/observability";
import { ControlPlaneError } from "@/lib/control-plane/errors";
import type { SocialReadContext } from "@/lib/control-plane/adapters/social";
import type { Permission } from "@/types/auth";

export function socialRead(
  capability: string,
  permission: Permission,
  run: (req: Request, ctx: SocialReadContext) => Promise<unknown>,
): (req: Request) => Promise<Response> {
  return withApiHandler(async (req) => {
    const operator = await resolveOperatorContext(req);
    const decision = authorize(operator, capability, permission);
    if (!decision.allowed) {
      observeSecurity("authorization_denied", {
        operatorId: operator.operatorId,
        capability,
        reasonCode: decision.reasonCode,
        correlationId: operator.correlationId,
      });
      throw new ConsoleApiError(403, "permission_denied", { upstreamCode: permission });
    }
    const ctx: SocialReadContext = {
      operatorToken: readSessionCookie(),
      correlationId: operator.correlationId,
    };
    try {
      const data = await run(req, ctx);
      return Response.json(data, { headers: { "cache-control": "no-store" } });
    } catch (e) {
      if (e instanceof ControlPlaneError) {
        // Preserve the canonical distinction (unavailable/timeout/unauthorized/…).
        throw new ConsoleApiError(e.httpStatus, e.code, { upstreamCode: e.code });
      }
      throw e;
    }
  });
}

/** Extract a path id from a dynamic route request URL. */
export function idFromUrl(url: string): string {
  const parts = new URL(url).pathname.split("/").filter(Boolean);
  return decodeURIComponent(parts[parts.length - 1] ?? "");
}
