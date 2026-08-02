import { withApiHandler, requirePermission } from "@/lib/api-guard";
import { robozaoOperationCommand } from "@/lib/robozao";

export const POST = withApiHandler(async (req: Request) => {
  await requirePermission("dlq.replay");
  const parts = new URL(req.url).pathname.split("/");
  const index = parts.indexOf("dlq");
  const dlqId = parts[index + 1] ?? "";
  if (!/^[a-fA-F0-9-]{36}$/.test(dlqId)) {
    return Response.json({ error: "invalid_id" }, { status: 400 });
  }
  const result = await robozaoOperationCommand(
    { action_id: "platform.dlq.replay", payload: { dlq_id: dlqId } },
    req.headers.get("idempotency-key") ?? `dlq-replay-${dlqId}`,
    req.headers.get("x-request-id") ?? "",
  );
  return Response.json(
    { operation: result.payload, approval_required: true },
    { status: result.status },
  );
});
