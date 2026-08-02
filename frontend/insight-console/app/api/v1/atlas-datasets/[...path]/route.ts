import { requireOperator, withApiHandler } from "@/lib/api-guard";
import { atlasIntelligenceCall } from "@/lib/data-intelligence";

async function handler(req: Request): Promise<Response> {
  const operator = await requireOperator();
  const url = new URL(req.url);
  const marker = "/atlas-datasets/";
  const path = decodeURIComponent(url.pathname.split(marker)[1] ?? "");
  const mutation = req.method !== "GET";
  if (mutation && operator.role !== "SuperAdmin") {
    return Response.json({ error: "superadmin_required" }, { status: 403 });
  }
  const body = mutation ? await req.json() : undefined;
  const upstream = await atlasIntelligenceCall(
    `datasets/${path}${url.search}`,
    req.method,
    body,
    operator.username ?? operator.displayName,
  );
  const headers = new Headers(upstream.headers);
  headers.set("cache-control", "no-store");
  return new Response(await upstream.text(), { status: upstream.status, headers });
}

export const GET = withApiHandler(handler);
export const POST = withApiHandler(handler);
