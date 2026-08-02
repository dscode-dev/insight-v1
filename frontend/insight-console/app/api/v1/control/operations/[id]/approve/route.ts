import { ConsoleApiError } from "@/lib/admin-api";
import { requireOperator, withApiHandler } from "@/lib/api-guard";
import { robozaoOperationApprove } from "@/lib/robozao";

export const POST = withApiHandler(async (req: Request) => {
  await requireOperator();
  const parts = new URL(req.url).pathname.split("/");
  const index = parts.indexOf("operations");
  const operationId = parts[index + 1] ?? "";
  if (!/^[a-zA-Z0-9-]+$/.test(operationId)) {
    throw new ConsoleApiError(400, "invalid_operation_id");
  }
  return Response.json({ operation: await robozaoOperationApprove(operationId) }, { status: 202 });
});
