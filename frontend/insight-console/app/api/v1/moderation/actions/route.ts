// /api/v1/moderation/actions — audited moderation action log + execution.
//   GET  → recent actions (audit trail)
//   POST → take an action (dismiss/remove/restore/suspend/ban).
//
// CONSOLE-SECURITY-A0: attribution is now the canonical OperatorContext (verified
// server session — the browser CANNOT declare the moderator). Authorization uses
// the capability seam (social.content.moderate + the real per-action permission).
// Canonical administrative audit is emitted (AUTHORIZED/DENIED → COMPLETED/FAILED).
// The upstream `moderator_id` is populated server-side (compatibility bridge) from
// the trusted context — never from client input. Moderation behavior is unchanged;
// no new capability is added.

import { withApiHandler, requirePermission } from "@/lib/api-guard";
import { ConsoleApiError } from "@/lib/admin-api";
import { fetchActions, postAction, ACTION_PERMISSION } from "@/lib/moderation";
import {
  resolveOperatorContext,
  assertNoClientActor,
  authorize,
  AdministrativeAudit,
  observeSecurity,
} from "@/lib/control-plane/security";

const CAPABILITY = "social.content.moderate";

export const GET = withApiHandler(async (req) => {
  await requirePermission("feed.read");
  const limit = Number(new URL(req.url).searchParams.get("limit") ?? "50");
  const data = await fetchActions(Number.isFinite(limit) ? limit : 50);
  return Response.json(data, { headers: { "cache-control": "no-store" } });
});

export const POST = withApiHandler(async (req) => {
  const operator = await resolveOperatorContext(req);

  let body: {
    action?: string;
    report_id?: string;
    target_type?: string;
    target_id?: string;
    note?: string;
    suspend_days?: number;
    moderator_id?: string; // ignored for authoritative attribution
  };
  try {
    body = await req.json();
  } catch {
    throw new ConsoleApiError(400, "invalid_json");
  }
  // Any client-supplied actor field is stripped (never authoritative).
  if (body.moderator_id !== undefined) {
    observeSecurity("legacy_attribution_ignored", {
      operatorId: operator.operatorId,
      field: "moderator_id",
      correlationId: operator.correlationId,
    });
  }
  assertNoClientActor(body as Record<string, unknown>);

  const action = body.action ?? "";
  const perm = ACTION_PERMISSION[action];
  if (!perm) throw new ConsoleApiError(400, "invalid_action");

  const target = {
    environmentId: "google-cloud",
    serviceId: "social",
    resourceType: body.target_type ?? null,
    resourceId: body.target_id ?? null,
  };

  // Authorization DECISION via the seam (registry presence never authorizes).
  const decision = authorize(operator, CAPABILITY, perm, target);
  const intent = await AdministrativeAudit.decision(operator, decision, {
    target,
    metadata: { action, target_type: body.target_type ?? null },
  });
  if (!decision.allowed) {
    observeSecurity("authorization_denied", {
      operatorId: operator.operatorId,
      capability: CAPABILITY,
      reasonCode: decision.reasonCode,
      correlationId: operator.correlationId,
    });
    throw new ConsoleApiError(403, "permission_denied", { upstreamCode: perm });
  }
  observeSecurity("authorization_allowed", {
    operatorId: operator.operatorId,
    capability: CAPABILITY,
    correlationId: operator.correlationId,
  });
  // FAIL-CLOSED: moderation is a high-risk mutation. If the AUTHORIZED intent
  // could not be durably recorded on the canonical spine, do NOT mutate.
  if (!intent.persisted) {
    throw new ConsoleApiError(503, "audit_unavailable", { upstreamCode: "audit_intent_not_durable" });
  }

  if (!body.target_type || !body.target_id) {
    throw new ConsoleApiError(400, "target_required");
  }

  try {
    await postAction({
      // Compatibility bridge: upstream contract requires moderator_id; we supply
      // it from the TRUSTED context (username??id), never from the browser.
      moderator_id: operator.operatorUsername ?? operator.operatorId,
      action,
      report_id: body.report_id,
      target_type: body.target_type,
      target_id: body.target_id,
      note: body.note,
      suspend_days: body.suspend_days,
    });
    await AdministrativeAudit.outcome(operator, decision, "COMPLETED", {
      target,
      metadata: { action },
    });
    return new Response(null, { status: 204 });
  } catch (err) {
    const errorCode = err instanceof ConsoleApiError ? err.upstreamCode ?? err.message : "upstream_error";
    const retryable = err instanceof ConsoleApiError ? err.status >= 500 : true;
    await AdministrativeAudit.outcome(operator, decision, "FAILED", {
      target,
      errorCode,
      retryable,
      metadata: { action },
    });
    throw err;
  }
});
