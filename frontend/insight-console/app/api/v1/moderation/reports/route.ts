// GET /api/v1/moderation/reports — moderation queue (Store-A Part 6).
// Forwards filters (status/reason/target_type/target_id/reporter_id/limit/
// offset) to the Gateway admin API. Read-gated on feed.read.

import { withApiHandler, requirePermission } from "@/lib/api-guard";
import { fetchReports } from "@/lib/moderation";

const ALLOWED = new Set([
  "status",
  "reason",
  "target_type",
  "target_id",
  "reporter_id",
  "limit",
  "offset",
]);

export const GET = withApiHandler(async (req) => {
  await requirePermission("feed.read");
  const incoming = new URL(req.url).searchParams;
  const out = new URLSearchParams();
  for (const [k, v] of incoming) {
    if (ALLOWED.has(k) && v) out.set(k, v);
  }
  const data = await fetchReports(out.toString());
  return Response.json(data, { headers: { "cache-control": "no-store" } });
});
