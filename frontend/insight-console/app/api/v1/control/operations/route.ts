import { ConsoleApiError } from "@/lib/admin-api";
import { requireOperator, withApiHandler } from "@/lib/api-guard";
import { robozaoOperationCommand, robozaoOps } from "@/lib/robozao";

export const dynamic = "force-dynamic";

export const GET = withApiHandler(async (req: Request) => {
  await requireOperator();
  const source = new URL(req.url).searchParams;
  const query = new URLSearchParams();
  for (const key of ["action_id", "status", "limit"]) {
    const value = source.get(key);
    if (value) query.set(key, value);
  }
  return Response.json(await robozaoOps("commands", query.toString()), {
    headers: { "cache-control": "no-store" },
  });
});

export const POST = withApiHandler(async (req: Request) => {
  await requireOperator();
  const idempotencyKey = req.headers.get("idempotency-key")?.trim() ?? "";
  if (!idempotencyKey) throw new ConsoleApiError(400, "idempotency_key_required");
  const body = await req.json().catch(() => ({})) as Record<string, unknown>;
  if (typeof body.action_id !== "string" || !body.action_id.trim()) {
    throw new ConsoleApiError(400, "action_id_required");
  }
  const result = await robozaoOperationCommand(
    body,
    idempotencyKey,
    req.headers.get("x-correlation-id") ?? req.headers.get("x-request-id") ?? "",
  );
  return Response.json(
    { operation: result.payload, idempotent_replay: result.replay },
    { status: result.status },
  );
});
