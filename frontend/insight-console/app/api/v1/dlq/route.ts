// GET /api/v1/dlq — Sprint 8.
// Lists dead-letter entries via the admin API /v1/console/dlq. Permission:
// dlq.read.
//
// Query params (passthrough): provider, failure_type, unreplayed,
// limit, offset.

import { z } from "zod";

import { withApiHandler, requirePermission } from "@/lib/api-guard";
import { adminJson, ConsoleApiError } from "@/lib/admin-api";
import { readSessionCookie } from "@/lib/session";

const dlqItemSchema = z.object({
  id: z.string(),
  job_id: z.string(),
  provider_id: z.string(),
  competition_id: z.string(),
  sync_type: z.string(),
  reason: z.string(),
  failure_type: z.string(),
  attempts: z.number(),
  failed_at: z.string(),
  replayed_at: z.string().nullable().optional(),
});

const dlqPageSchema = z.object({
  items: z.array(dlqItemSchema),
  limit: z.number(),
  offset: z.number(),
});

export const GET = withApiHandler(async (req) => {
  await requirePermission("dlq.read");
  const token = readSessionCookie();
  const url = new URL(req.url);
  // Pass through whitelisted filters only — never forward unknown
  // query params upstream.
  const allowed = ["provider", "failure_type", "unreplayed", "limit", "offset"];
  const upstream = new URLSearchParams();
  for (const key of allowed) {
    const v = url.searchParams.get(key);
    if (v !== null) upstream.set(key, v);
  }
  const qs = upstream.toString();
  const path = `/v1/console/dlq${qs ? `?${qs}` : ""}`;
  // CONSOLE-OPS-A Stage 6/13: the Gateway DLQ endpoint may not be deployed yet
  // (upstream_404). Never surface a raw upstream error — degrade to an explained
  // empty-state so the page shows "feature not yet available", not an error.
  try {
    const body = await adminJson(path, dlqPageSchema, {
      operatorToken: token ?? undefined,
      correlationId: req.headers.get("x-request-id") ?? undefined,
    });
    return Response.json(body);
  } catch (e) {
    const status = e instanceof ConsoleApiError ? e.status : 502;
    return Response.json(
      {
        items: [],
        limit: 0,
        offset: 0,
        unavailable: true,
        feature_status: status === 404 ? "not_yet_available" : "upstream_unavailable",
        detail:
          status === 404
            ? "Gateway dead-letter endpoint (/v1/console/dlq) is not deployed yet — no DLQ data to show."
            : "The dead-letter source is temporarily unavailable.",
      },
      { headers: { "cache-control": "no-store" } },
    );
  }
});
