import { ConsoleApiError } from "@/lib/admin-api";
import { requirePermission, withApiHandler } from "@/lib/api-guard";
import { robozaoOperationCommand } from "@/lib/robozao";

export const POST = withApiHandler(async (req: Request) => {
  await requirePermission("user.force_logout");
  const parts = new URL(req.url).pathname.split("/");
  const index = parts.indexOf("users");
  const userId = parts[index + 1] ?? "";
  if (!/^[a-fA-F0-9-]{36}$/.test(userId)) {
    return Response.json({ error: "invalid_user_id" }, { status: 400 });
  }
  const idempotencyKey =
    req.headers.get("idempotency-key") ?? req.headers.get("x-request-id") ?? "";
  if (!idempotencyKey) throw new ConsoleApiError(400, "idempotency_key_required");
  const result = await robozaoOperationCommand(
    { action_id: "identity.session.revoke", payload: { user_id: userId } },
    idempotencyKey,
    req.headers.get("x-request-id") ?? "",
  );
  return Response.json(
    { operation: result.payload, approval_required: true },
    { status: result.status },
  );
});
