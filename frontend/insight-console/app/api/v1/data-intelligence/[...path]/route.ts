import { requireOperator, withApiHandler } from "@/lib/api-guard";
import { ConsoleApiError } from "@/lib/admin-api";
import { atlasIntelligenceCall } from "@/lib/data-intelligence";
import { operatorContextFromOperator } from "@/lib/control-plane/security";
import { explorerPrivilegedCall } from "@/lib/control-plane/adapters/explorer-privileged";

async function proxy(req: Request): Promise<Response> {
  const operator = await requireOperator();
  // Canonical operator context — Explorer attribution derives from THIS, never
  // from the browser (CONSOLE-SECURITY-A1, Stage 10).
  const ctx = operatorContextFromOperator(operator, req);
  const url = new URL(req.url);
  const marker = "/data-intelligence/";
  const path = decodeURIComponent(url.pathname.split(marker)[1] ?? "");
  const body = req.method === "GET" ? undefined : await req.json();
  if (req.method !== "GET") {
    const permissions = new Set(operator.permissions);
    const allowed =
      (path === "sources/enable" && permissions.has("provider.enable"))
      || (path === "sources/disable" && permissions.has("provider.disable"))
      || permissions.has("config.write");
    if (!allowed) throw new ConsoleApiError(403, "permission_denied");
  }
  if (path.startsWith("atlas/")) {
    // Atlas 1.0.0 frozen, read-only, service-token identity — not operator-bound.
    return atlasIntelligenceCall(path.slice("atlas/".length), req.method, body);
  }
  const query = url.search ? url.search : "";
  // Operator-bound typed adapter (server-derived X-Operator + correlation).
  return explorerPrivilegedCall(ctx, path + query, req.method, body);
}

export const GET = withApiHandler(proxy);
export const POST = withApiHandler(proxy);
export const PUT = withApiHandler(proxy);
