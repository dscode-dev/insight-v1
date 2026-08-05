// /api/v1/quality-gate/* — Atlas Quality Gate, via insight-console-api.
//
// WHY THIS EXISTS AS ITS OWN ROUTE rather than riding the generic
// /api/v1/console-api/[...path] proxy: recording a promotion decision is
// a governed mutation. `ATLAS_V1_FROZEN.md` makes human approval
// mandatory before any detector/heuristic change is promoted against the
// frozen baseline, so the decision has to pass the canonical
// capability → authorize → audit(intent) → mutate → audit(outcome)
// spine (same shape as moderation/actions/route.ts, the reference
// implementation). The generic proxy has no capability seam and no audit
// — a decision taken through it would leave no console-side trace.
//
// Reads still go through this file so the screen has one base path, but
// they take the ordinary read permission and emit no administrative
// audit.

import { ConsoleApiError } from "@/lib/admin-api";
import { requireOperator, requirePermission, withApiHandler } from "@/lib/api-guard";
import { consoleApiCall } from "@/lib/control-plane/adapters/console-api";
import { classifyQualityGateWrite } from "@/lib/control-plane/quality-gate-routing";
import {
  AdministrativeAudit,
  assertNoClientActor,
  authorize,
  observeSecurity,
  operatorContextFromOperator,
} from "@/lib/control-plane/security";

const PROMOTE_CAPABILITY = "atlas.replay.promote";

/** Mutating a replay's promotion state is a configuration write. */
const PROMOTE_PERMISSION = "config.write" as const;

function pathOf(req: Request): { path: string; search: string } {
  const url = new URL(req.url);
  const marker = "/quality-gate/";
  return {
    path: decodeURIComponent(url.pathname.split(marker)[1] ?? ""),
    search: url.search || "",
  };
}

export const GET = withApiHandler(async (req) => {
  await requirePermission("config.read");
  const operator = await requireOperator();
  const { path, search } = pathOf(req);
  return consoleApiCall(
    operatorContextFromOperator(operator, req),
    `quality-gate/${path}${search}`,
  );
});

export const DELETE = withApiHandler(async (req) => {
  await requirePermission(PROMOTE_PERMISSION);
  const operator = await requireOperator();
  const { path, search } = pathOf(req);
  return consoleApiCall(
    operatorContextFromOperator(operator, req),
    `quality-gate/${path}${search}`,
    "DELETE",
  );
});

export const POST = withApiHandler(async (req) => {
  const operator = await requireOperator();
  const ctx = operatorContextFromOperator(operator, req);
  const { path, search } = pathOf(req);

  let body: Record<string, unknown>;
  try {
    body = (await req.json()) as Record<string, unknown>;
  } catch {
    throw new ConsoleApiError(400, "invalid_json");
  }
  // A decision's author is derived server-side end to end: this context,
  // signed across to insight-console-api, forwarded to Atlas as
  // X-Operator. Nothing the browser sends can name the decider.
  assertNoClientActor(body);

  const route = classifyQualityGateWrite(path);
  if (route.kind === "refuse") {
    // Fails closed: a path that reaches a decision endpoint but does not
    // parse is refused outright, never demoted to the ungoverned branch.
    throw new ConsoleApiError(400, route.reason);
  }
  if (route.kind === "ordinary") {
    // Submitting or cancelling a replay — a normal operation, not a
    // governance act. No baseline is changed by running one.
    await requirePermission(PROMOTE_PERMISSION);
    return consoleApiCall(ctx, `quality-gate/${path}${search}`, "POST", body);
  }
  const executionId = route.executionId;

  const target = {
    environmentId: "google-cloud",
    serviceId: "atlas",
    resourceType: "replay",
    resourceId: executionId,
  };
  const metadata = {
    verdict: String(body.verdict ?? ""),
    // These two are the whole point of the audit record: an approval
    // taken AGAINST the gate's recommendation, or with no baseline to
    // diff against, is what a later reader most needs to find.
    override_recommendation: body.override_recommendation === true,
    acknowledge_no_baseline: body.acknowledge_no_baseline === true,
  };

  const decision = authorize(ctx, PROMOTE_CAPABILITY, PROMOTE_PERMISSION, target);
  const intent = await AdministrativeAudit.decision(ctx, decision, {
    target,
    metadata,
  });
  if (!decision.allowed) {
    observeSecurity("authorization_denied", {
      operatorId: ctx.operatorId,
      capability: PROMOTE_CAPABILITY,
      reasonCode: decision.reasonCode,
      correlationId: ctx.correlationId,
    });
    throw new ConsoleApiError(403, "permission_denied", {
      upstreamCode: PROMOTE_PERMISSION,
    });
  }
  observeSecurity("authorization_allowed", {
    operatorId: ctx.operatorId,
    capability: PROMOTE_CAPABILITY,
    correlationId: ctx.correlationId,
  });
  // FAIL-CLOSED. If the AUTHORIZED intent could not be durably recorded,
  // do NOT record the decision: an approval that exists in Atlas with no
  // console-side trail defeats the audit requirement that motivated the
  // whole screen.
  if (!intent.persisted) {
    throw new ConsoleApiError(503, "audit_unavailable", {
      upstreamCode: "audit_intent_not_durable",
    });
  }

  const response = await consoleApiCall(
    ctx,
    `quality-gate/${path}`,
    "POST",
    body,
  );

  if (response.ok) {
    await AdministrativeAudit.outcome(ctx, decision, "COMPLETED", {
      target,
      metadata,
    });
    return response;
  }

  // A refused decision is an OUTCOME, not an exception: the gate saying
  // "you must override explicitly" is the system working. Record it as
  // FAILED with the gate's own code, and pass the body through so the
  // screen can tell the operator what is required.
  const text = await response.text();
  let errorCode = `http_${response.status}`;
  try {
    const parsed = JSON.parse(text) as { code?: unknown; message?: unknown };
    if (typeof parsed.code === "string") {
      errorCode = parsed.code;
    }
  } catch {
    // Non-JSON refusal — keep the status-derived code.
  }
  await AdministrativeAudit.outcome(ctx, decision, "FAILED", {
    target,
    errorCode,
    retryable: response.status >= 500,
    metadata,
  });
  return new Response(text, {
    status: response.status,
    headers: {
      "content-type": response.headers.get("content-type") ?? "application/json",
      "cache-control": "no-store",
    },
  });
});
