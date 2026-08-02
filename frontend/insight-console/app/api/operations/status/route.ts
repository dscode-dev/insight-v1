// GET /api/operations/status
//
// Internal operations portal status. Browser code calls only this BFF route.
// Google Cloud state is accessed through Insight Gateway; Robozão services are
// accessed through internal adapters.

import { withApiHandler, requirePermission } from "@/lib/api-guard";
import { operationsSnapshot } from "@/lib/operations-adapters";

export const GET = withApiHandler(async () => {
  await requirePermission("console.access");
  const snapshot = await operationsSnapshot();
  return Response.json(snapshot, { headers: { "cache-control": "no-store" } });
});

