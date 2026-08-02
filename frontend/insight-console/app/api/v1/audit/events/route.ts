// GET /api/v1/audit/events — canonical Console administrative audit read surface
// (CONSOLE-SECURITY-A0, Stage 15).
//
// Reads the Console Control Plane audit spine (control_plane_audit_event). Distinct
// from GET /api/v1/audit, which reads the Gateway operator_audit_log. Authenticated
// + authorized (audit.read), paginated (keyset), deterministic order, whitelisted
// filters only (no arbitrary SQL-like filtering), safe serialization (no secrets).

import { requirePermission, withApiHandler } from "@/lib/api-guard";
import { getAuditRepository, type AuditQueryFilter } from "@/lib/control-plane/security";

export const dynamic = "force-dynamic";

function str(url: URL, key: string): string | undefined {
  const v = url.searchParams.get(key);
  return v === null || v === "" ? undefined : v;
}

export const GET = withApiHandler(async (req) => {
  await requirePermission("audit.read");
  const url = new URL(req.url);
  const limitRaw = Number(url.searchParams.get("limit") ?? "50");
  const filter: AuditQueryFilter = {
    correlationId: str(url, "correlation_id"),
    operator: str(url, "operator"),
    capability: str(url, "capability"),
    service: str(url, "service"),
    environment: str(url, "environment"),
    resourceId: str(url, "resource_id"),
    outcome: str(url, "outcome"),
    since: str(url, "since"),
    until: str(url, "until"),
    cursor: str(url, "cursor") ?? null,
    limit: Number.isFinite(limitRaw) ? limitRaw : 50,
  };
  const repo = getAuditRepository();
  const page = await repo.query(filter);
  return Response.json(
    { items: page.items, next_cursor: page.nextCursor, durable: repo.durable, spine: repo.kind },
    { headers: { "cache-control": "no-store" } },
  );
});
