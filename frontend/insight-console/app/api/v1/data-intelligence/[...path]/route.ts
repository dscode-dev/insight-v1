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
  const hasBody = req.method !== "GET" && req.method !== "DELETE";
  const body = hasBody ? await req.json() : undefined;
  if (req.method !== "GET") {
    const permissions = new Set(operator.permissions);
    const allowed =
      (path === "sources/enable" && permissions.has("provider.enable"))
      || (path === "sources/disable" && permissions.has("provider.disable"))
      || permissions.has("config.write");
    if (!allowed) throw new ConsoleApiError(403, "permission_denied");
  }
  const query = url.search ? url.search : "";
  if (path.startsWith("atlas/")) {
    // A query PRECISA ir junto: `?simular=true` é o que separa uma
    // validação em seco de uma gravação, e descartá-la aqui faria a tela
    // gravar quando o operador pediu simulação. O caminho continua sendo
    // filtrado pela allow-list do Control Plane.
    //
    // (O comentário anterior dizia "Atlas read-only, não vinculado ao
    // operador". Deixou de valer com a ingestão: o Control Plane assina
    // X-Operator a partir da sessão, e o Atlas grava quem ingeriu.)
    return atlasIntelligenceCall(
      path.slice("atlas/".length) + query,
      req.method,
      body,
    );
  }
  // Operator-bound typed adapter (server-derived X-Operator + correlation).
  return explorerPrivilegedCall(ctx, path + query, req.method, body);
}

export const GET = withApiHandler(proxy);
export const POST = withApiHandler(proxy);
export const PUT = withApiHandler(proxy);
export const DELETE = withApiHandler(proxy);
