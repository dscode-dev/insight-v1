// GET /api/health — dependency-free liveness probe for container health
// checks (ML-C Step 0). Returns 200 without touching upstream services, so
// the SanninJiraiya compose healthcheck reflects the Console process itself.

export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({
    status: "ok",
    service: "insight-console",
    ts: new Date().toISOString(),
  });
}
