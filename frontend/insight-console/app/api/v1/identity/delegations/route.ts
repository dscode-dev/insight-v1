// /api/v1/identity/delegations — CONSOLE-IDENTITY-A.
// GET: the operator's own grants. POST: create an explicit, revocable grant.
// The Gateway is the authority; operator identity is derived from the session.
import { ConsoleApiError } from "@/lib/admin-api";
import { requireOperator, withApiHandler } from "@/lib/api-guard";
import { readSessionCookie } from "@/lib/session";
import { assertNoClientActor } from "@/lib/control-plane/security/operator-context";
import { grantDelegation, listDelegations } from "@/lib/control-plane/adapters/identity";

export const dynamic = "force-dynamic";

export const GET = withApiHandler(async (req) => {
  await requireOperator();
  const items = await listDelegations(readSessionCookie(), req.headers.get("x-request-id"));
  return Response.json({ items, count: items.length }, { headers: { "cache-control": "no-store" } });
});

export const POST = withApiHandler(async (req) => {
  await requireOperator();
  let raw: Record<string, unknown> = {};
  try {
    const text = await req.text();
    if (text) raw = JSON.parse(text) as Record<string, unknown>;
  } catch {
    throw new ConsoleApiError(400, "invalid_json");
  }
  // Never trust browser-supplied operator/identity/actor fields.
  assertNoClientActor(raw);
  const subjectType = raw["subject_type"] === "agent" ? "agent" : "official_identity";
  const mode = raw["mode"] === "act_through_agent" ? "act_through_agent" : "act_as_identity";
  const subjectId = typeof raw["subject_id"] === "string" ? (raw["subject_id"] as string) : "";
  const reason = typeof raw["reason"] === "string" ? (raw["reason"] as string).trim() : "";
  if (!subjectId || !reason) throw new ConsoleApiError(400, "subject_and_reason_required");
  const result = await grantDelegation(readSessionCookie(), req.headers.get("x-request-id"), {
    subjectType, subjectId, mode, reason,
    publicActor: typeof raw["public_actor"] === "string" ? (raw["public_actor"] as string) : undefined,
    expiresAt: typeof raw["expires_at"] === "string" ? (raw["expires_at"] as string) : undefined,
  });
  return Response.json(result, { status: 201, headers: { "cache-control": "no-store" } });
});
