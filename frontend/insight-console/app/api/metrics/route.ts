// GET /api/metrics — console_* counters, Prometheus text format.
// No session gate: scraped by Prometheus inside the network (same
// posture as every other service's /metrics).

import { renderMetrics } from "@/lib/console-metrics";

export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  return new Response(renderMetrics(), {
    headers: { "Content-Type": "text/plain; version=0.0.4; charset=utf-8" },
  });
}
