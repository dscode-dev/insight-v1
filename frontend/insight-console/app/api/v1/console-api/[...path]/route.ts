import { requireOperator, withApiHandler } from "@/lib/api-guard";
import { consoleApiCall } from "@/lib/control-plane/adapters/console-api";
import { operatorContextFromOperator } from "@/lib/control-plane/security";

/**
 * Thin proxy to insight-console-api (the console backend).
 *
 * Identity is resolved HERE and signed across — the backend never sees a
 * browser-supplied actor. Keeping the browser on this origin means the
 * session cookie and CSP are unchanged, and adopting the backend needs
 * no edge-proxy reconfiguration.
 */
async function proxy(req: Request): Promise<Response> {
  const operator = await requireOperator();
  const ctx = operatorContextFromOperator(operator, req);
  const url = new URL(req.url);
  const marker = "/console-api/";
  const path = decodeURIComponent(url.pathname.split(marker)[1] ?? "");
  const hasBody = req.method !== "GET" && req.method !== "DELETE";
  const body = hasBody ? await req.json() : undefined;
  return consoleApiCall(path + (url.search || ""), req.method, body);
}

export const GET = withApiHandler(proxy);
export const POST = withApiHandler(proxy);
export const PUT = withApiHandler(proxy);
export const DELETE = withApiHandler(proxy);
