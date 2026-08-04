const EXPLORER_API_BASE_URL =
  process.env.EXPLORER_API_BASE_URL ?? "http://insight-explorer:8090";
const EXPLORER_OPS_TOKEN = process.env.EXPLORER_OPS_TOKEN ?? "";
const ATLAS_API_BASE_URL =
  process.env.ATLAS_API_BASE_URL ?? "http://atlas:8085";
const ATLAS_INTERNAL_TOKEN = process.env.ATLAS_INTERNAL_TOKEN ?? "";

export async function explorerCall(
  path: string,
  method: string,
  body: unknown,
  actor: string,
  correlationId?: string,
): Promise<Response> {
  if (!EXPLORER_OPS_TOKEN) {
    return Response.json({ detail: "explorer_ops_token_missing" }, { status: 503 });
  }
  return serviceCall(EXPLORER_API_BASE_URL, `/explorer/${path}`, method, body, {
    "X-Operator": actor,
    "X-Ops-Token": EXPLORER_OPS_TOKEN,
    ...(correlationId ? { "X-Request-Id": correlationId } : {}),
  });
}

export async function atlasIntelligenceCall(
  path: string,
  method: string,
  body: unknown,
  actor?: string,
): Promise<Response> {
  if (!ATLAS_INTERNAL_TOKEN) {
    return Response.json({ detail: "atlas_internal_token_missing" }, { status: 503 });
  }
  const normalized = path.replace(/^\/+/, "");
  const runtimePaths = new Set([
    "ingestion",
    "reasoning",
    "intelligence-graph",
    "conflicts",
    "behaviors",
    "patterns",
    "signals",
    "trends",
    "market",
    "uncertainty",
    "memory",
    "head-to-head",
    "team-memory",
  ]);
  return serviceCall(
    ATLAS_API_BASE_URL,
    runtimePaths.has(normalized) || normalized.startsWith("datasets")
      ? `/atlas/${normalized}`
      : `/v1/internal/intelligence/${normalized}`,
    method,
    body,
    {
      "X-Internal-Token": ATLAS_INTERNAL_TOKEN,
      ...(actor ? { "X-Operator": actor } : {}),
    },
  );
}

async function serviceCall(
  base: string,
  path: string,
  method: string,
  body: unknown,
  headers: Record<string, string>,
): Promise<Response> {
  const upstream = await fetch(`${base.replace(/\/+$/, "")}${path}`, {
    method,
    cache: "no-store",
    signal: AbortSignal.timeout(10_000),
    headers: {
      Accept: "application/json",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await upstream.text();
  return new Response(text, {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/json",
      "cache-control": "no-store",
    },
  });
}
