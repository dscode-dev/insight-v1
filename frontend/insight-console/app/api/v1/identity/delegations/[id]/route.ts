// DELETE /api/v1/identity/delegations/{id} — CONSOLE-IDENTITY-A. Revoke a grant
// (operator can only revoke their own; the Gateway enforces ownership).
import { requireOperator, withApiHandler } from "@/lib/api-guard";
import { readSessionCookie } from "@/lib/session";
import { revokeDelegation } from "@/lib/control-plane/adapters/identity";

export const dynamic = "force-dynamic";

export const DELETE = withApiHandler(async (req) => {
  await requireOperator();
  // withApiHandler forwards only `req`; read the id from the path (last segment).
  const parts = new URL(req.url).pathname.split("/").filter(Boolean);
  const id = decodeURIComponent(parts[parts.length - 1] ?? "");
  const revoked = await revokeDelegation(readSessionCookie(), req.headers.get("x-request-id"), id);
  return Response.json({ delegation_id: id, revoked }, { headers: { "cache-control": "no-store" } });
});
