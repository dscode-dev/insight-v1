// GET /api/ops/robozao/status — private Robozão Gateway reachability.
//
// Console consumes Robozão as a second source while Gateway remains the
// identity authority. This route forwards the opaque Gateway operator session
// to Robozão Gateway; it never validates credentials locally.

import { withApiHandler, requirePermission } from "@/lib/api-guard";
import { robozaoStatus } from "@/lib/robozao";

export const GET = withApiHandler(async () => {
  await requirePermission("console.access");
  try {
    const status = await robozaoStatus();
    return Response.json(status, { headers: { "cache-control": "no-store" } });
  } catch (err) {
    return Response.json(
      {
        vpn_connected: false,
        robozao_reachable: false,
        operator_validated: false,
        services: {},
        registry: [],
        checked_at: new Date().toISOString(),
        source: "robozao-gateway",
        detail: err instanceof Error ? err.message : "robozao_unreachable",
      },
      { status: 200, headers: { "cache-control": "no-store" } },
    );
  }
});

