// GET /api/v1/platform/health — Sprint 8.
// Proxies the admin API /v1/health/platform. Read by the Dashboard page
// every 5s via SWR.

import { z } from "zod";

import { withApiHandler, requireOperator } from "@/lib/api-guard";
import { adminJson } from "@/lib/admin-api";
import { readSessionCookie } from "@/lib/session";

const healthSchema = z.object({
  sports_hub: z.object({
    status: z.string(),
    code: z.number(),
    error: z.string().nullable().optional(),
  }),
  atlas: z.object({
    status: z.string(),
    code: z.number(),
    error: z.string().nullable().optional(),
  }),
  gateway: z.object({ status: z.string() }),
});

export const GET = withApiHandler(async (req) => {
  await requireOperator();
  const token = readSessionCookie();
  const body = await adminJson("/v1/health/platform", healthSchema, {
    operatorToken: token ?? undefined,
    correlationId: req.headers.get("x-request-id") ?? undefined,
  });
  return Response.json(body);
});
