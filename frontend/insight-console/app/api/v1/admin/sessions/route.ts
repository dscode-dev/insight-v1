// GET /api/v1/admin/sessions — CONSOLE-OPS-A2 Stage 8.
// Read-only session counts (user + operator, active/revoked) via the Gateway
// console admin endpoint (/v1/console/admin/sessions). Degrades gracefully.

import { withApiHandler, requirePermission } from "@/lib/api-guard";
import { adminFetch, ConsoleApiError } from "@/lib/admin-api";
import { readSessionCookie } from "@/lib/session";

export const GET = withApiHandler(async (req) => {
  await requirePermission("console.access");
  const token = readSessionCookie();
  try {
    const res = await adminFetch("/v1/console/admin/sessions", {
      operatorToken: token ?? undefined,
      correlationId: req.headers.get("x-request-id") ?? undefined,
    });
    if (!res.ok) throw new ConsoleApiError(res.status, `upstream_${res.status}`);
    return Response.json(await res.json(), { headers: { "cache-control": "no-store" } });
  } catch (e) {
    const status = e instanceof ConsoleApiError ? e.status : 502;
    return Response.json(
      {
        user_sessions: { active: 0, revoked: 0 },
        operator_sessions: { active: 0, revoked: 0 },
        unavailable: true,
        feature_status: status === 404 ? "not_yet_available" : "upstream_unavailable",
        detail:
          status === 404
            ? "Gateway /v1/console/admin/sessions not deployed yet — rebuild the gateway image to enable."
            : "Session source temporarily unavailable.",
      },
      { headers: { "cache-control": "no-store" } },
    );
  }
});
