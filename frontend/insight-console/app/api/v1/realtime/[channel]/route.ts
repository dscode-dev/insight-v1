import { requireOperator, withApiHandler } from "@/lib/api-guard";
import { consoleApiStream } from "@/lib/control-plane/adapters/console-api";
import { operatorContextFromOperator } from "@/lib/control-plane/security";

/**
 * Server-Sent Events, piped from insight-console-api.
 *
 * Replaces client-side `setInterval` polling. The backend polls each
 * upstream ONCE per interval no matter how many tabs are subscribed, so
 * platform load stops scaling with the number of open consoles.
 *
 * `dynamic`/`revalidate` are pinned because a cached SSE response would
 * be permanently broken rather than merely stale.
 */
export const dynamic = "force-dynamic";
export const revalidate = 0;

async function stream(req: Request): Promise<Response> {
  const operator = await requireOperator();
  const ctx = operatorContextFromOperator(operator, req);
  // The channel is read from the path rather than the route params so
  // this stays compatible with withApiHandler's single-argument shape.
  const segments = new URL(req.url).pathname.split("/").filter(Boolean);
  const channel = decodeURIComponent(segments[segments.length - 1] ?? "");
  // req.signal aborts when the browser disconnects, which tears down the
  // upstream subscription and lets an idle channel stop polling.
  return consoleApiStream(channel, req.signal);
}

export const GET = withApiHandler(stream);
