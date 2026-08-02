// GET /api/v1/providers/status — Sprint 8.
// Proxies the admin API /v1/providers/status. Permission: provider.read.

import { z } from "zod";

import { withApiHandler, requirePermission } from "@/lib/api-guard";
import { adminJson } from "@/lib/admin-api";
import { readSessionCookie } from "@/lib/session";

const hubProxySchema = z.object({
  upstream_ok: z.boolean(),
  upstream_url: z.string(),
  status_code: z.number(),
  data: z.unknown().nullable().optional(),
  error: z.string().nullable().optional(),
});

export const GET = withApiHandler(async (req) => {
  await requirePermission("provider.read");
  const token = readSessionCookie();
  const body = await adminJson("/v1/providers/status", hubProxySchema, {
    operatorToken: token ?? undefined,
    correlationId: req.headers.get("x-request-id") ?? undefined,
  });
  return Response.json(body);
});
