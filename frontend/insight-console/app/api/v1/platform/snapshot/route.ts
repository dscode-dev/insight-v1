// GET /api/v1/platform/snapshot — canonical server-assembled platform state.
//
// The Console BFF (not the browser) assembles distributed truth here: registries
// + typed adapters, bounded concurrency, per-source attribution, honest partial
// state. HTTP 200 with partial=true is a MODELED partial result (sources carry
// their own state); it is not a silent fallback.

import { requirePermission, withApiHandler } from "@/lib/api-guard";
import { PlatformSnapshotService } from "@/lib/control-plane";
import { readSessionCookie } from "@/lib/session";

export const dynamic = "force-dynamic";

export const GET = withApiHandler(async (req) => {
  await requirePermission("console.access");
  const correlationId = req.headers.get("x-request-id");
  const snapshot = await PlatformSnapshotService.generate({
    correlationId,
    operatorToken: readSessionCookie(),
  });
  return Response.json(snapshot, { headers: { "cache-control": "no-store" } });
});
