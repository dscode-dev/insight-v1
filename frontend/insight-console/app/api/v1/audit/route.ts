// GET /api/v1/audit — Sprint 8.
// Read the immutable audit log via the admin API /v1/console/audit.
// Permission: audit.read.

import { z } from "zod";

import { withApiHandler, requirePermission } from "@/lib/api-guard";
import { adminJson, ConsoleApiError } from "@/lib/admin-api";
import { readSessionCookie } from "@/lib/session";

const auditEventSchema = z.object({
  id: z.string().uuid(),
  action: z.string(),
  actor_id: z.string().uuid(),
  actor_display_name: z.string(),
  target_type: z.string(),
  target_id: z.string(),
  service: z.string(),
  request_id: z.string().nullable().optional(),
  correlation_id: z.string().nullable().optional(),
  metadata: z.record(z.string(), z.unknown()).default({}),
  created_at: z.string(),
});

const auditPageSchema = z.object({
  items: z.array(auditEventSchema),
  next_cursor: z.string().nullable().optional(),
  total: z.number().nullable().optional(),
});

const allowed = [
  "actor",
  "action",
  "service",
  "target_type",
  "target_id",
  "correlation_id",
  "since",
  "until",
  "cursor",
  "limit",
];

export const GET = withApiHandler(async (req) => {
  await requirePermission("audit.read");
  const token = readSessionCookie();
  const url = new URL(req.url);
  const upstream = new URLSearchParams();
  for (const key of allowed) {
    const v = url.searchParams.get(key);
    if (v !== null) upstream.set(key, v);
  }
  const qs = upstream.toString();
  const path = `/v1/console/audit${qs ? `?${qs}` : ""}`;
  // CONSOLE-OPS-A Stage 11/13: degrade gracefully if the Gateway audit endpoint
  // is not deployed yet (upstream_404) — explained empty-state, never an error.
  try {
    const body = await adminJson(path, auditPageSchema, {
      operatorToken: token ?? undefined,
      correlationId: req.headers.get("x-request-id") ?? undefined,
    });
    return Response.json(body);
  } catch (e) {
    const status = e instanceof ConsoleApiError ? e.status : 502;
    return Response.json(
      {
        items: [],
        next_cursor: null,
        total: 0,
        unavailable: true,
        feature_status: status === 404 ? "not_yet_available" : "upstream_unavailable",
        detail:
          status === 404
            ? "Gateway audit endpoint (/v1/console/audit) is not deployed yet — operator_audit_log exists in insight_auth and can back this once the endpoint ships."
            : "The audit source is temporarily unavailable.",
      },
      { headers: { "cache-control": "no-store" } },
    );
  }
});
