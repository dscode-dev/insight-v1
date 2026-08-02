// GET /api/cloud/services — live SanninJiraiya cloud-stack health (Console-X).
// Gated on the operator session; probes each service server-side over the
// insight-cloud network and returns real status/latency/version.

import { withApiHandler, requirePermission } from "@/lib/api-guard";
import { cloudServices } from "@/lib/cloud";

export const GET = withApiHandler(async () => {
  await requirePermission("console.access");
  const services = await cloudServices();
  const up = services.filter((s) => s.status === "up").length;
  return Response.json(
    {
      services,
      summary: { total: services.length, up, down: services.length - up },
      checked_at: new Date().toISOString(),
    },
    { headers: { "cache-control": "no-store" } },
  );
});
