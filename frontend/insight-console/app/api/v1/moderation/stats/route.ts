// GET /api/v1/moderation/stats — moderation dashboard aggregates (Store-A).

import { withApiHandler, requirePermission } from "@/lib/api-guard";
import { fetchStats } from "@/lib/moderation";

export const GET = withApiHandler(async () => {
  await requirePermission("feed.read");
  const data = await fetchStats();
  return Response.json(data, { headers: { "cache-control": "no-store" } });
});
