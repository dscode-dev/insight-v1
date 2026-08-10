// /api/v1/reminders/* — operational deadlines, via insight-console-api.
//
// Most of what this screen does is bookkeeping: record that a rotation
// happened, report a certificate's observed expiry, add a policy. Those
// take the ordinary config.write permission and nothing more.
//
// MUTING IS DIFFERENT, and is the only action here that goes through the
// capability → authorize → audit(intent) → mutate → audit(outcome) spine.
// Silencing a reminder does not change the deadline — it changes who
// finds out about it, and the reminders seeded today are about the mTLS
// pair and the Cloudflare tokens. "Why did nobody see this coming" is a
// question asked after the fact, and it can only be answered if the act
// of silencing left a trail. The other writes are recoverable by looking
// at the row; a mute is only visible while it lasts.

import { ConsoleApiError } from "@/lib/admin-api";
import { requireOperator, requirePermission, withApiHandler } from "@/lib/api-guard";
import { consoleApiCall } from "@/lib/control-plane/adapters/console-api";
import { classifyReminderWrite } from "@/lib/control-plane/reminders-routing";
import {
  AdministrativeAudit,
  assertNoClientActor,
  authorize,
  observeSecurity,
  operatorContextFromOperator,
} from "@/lib/control-plane/security";

const MUTE_CAPABILITY = "controlplane.reminder.mute";
const WRITE_PERMISSION = "config.write" as const;

function pathOf(req: Request): { path: string; search: string } {
  const url = new URL(req.url);
  const marker = "/reminders";
  const rest = url.pathname.split(marker)[1] ?? "";
  return {
    path: decodeURIComponent(rest.replace(/^\/+/, "")),
    search: url.search || "",
  };
}

export const GET = withApiHandler(async (req) => {
  await requirePermission("config.read");
  const { path, search } = pathOf(req);
  return consoleApiCall(`reminders${path ? `/${path}` : ""}${search}`);
});

export const POST = withApiHandler(async (req) => {
  await requirePermission(WRITE_PERMISSION);
  const operator = await requireOperator();
  const { path } = pathOf(req);

  let body: Record<string, unknown>;
  try {
    body = (await req.json()) as Record<string, unknown>;
  } catch {
    throw new ConsoleApiError(400, "invalid_json");
  }
  // Who did it is derived from the session, server-side, all the way to
  // the Control Plane. Nothing the browser sends names the operator.
  assertNoClientActor(body);

  const route = classifyReminderWrite(path);
  if (route.kind === "refuse") {
    throw new ConsoleApiError(400, route.reason);
  }
  if (route.kind === "ordinary") {
    return consoleApiCall(`reminders${path ? `/${path}` : ""}`, "POST", body);
  }
  const slug = route.slug;

  const ctx = operatorContextFromOperator(operator, req);
  const target = {
    environmentId: "robozao",
    serviceId: "console-api",
    resourceType: "reminder",
    resourceId: slug,
  };
  const metadata = {
    muted_until: String(body.until ?? ""),
    notes: typeof body.notes === "string" ? body.notes : "",
  };

  const decision = authorize(ctx, MUTE_CAPABILITY, WRITE_PERMISSION, target);
  const intent = await AdministrativeAudit.decision(ctx, decision, {
    target,
    metadata,
  });
  if (!decision.allowed) {
    observeSecurity("authorization_denied", {
      operatorId: ctx.operatorId,
      capability: MUTE_CAPABILITY,
      reasonCode: decision.reasonCode,
      correlationId: ctx.correlationId,
    });
    throw new ConsoleApiError(403, "permission_denied", {
      upstreamCode: WRITE_PERMISSION,
    });
  }
  observeSecurity("authorization_allowed", {
    operatorId: ctx.operatorId,
    capability: MUTE_CAPABILITY,
    correlationId: ctx.correlationId,
  });
  // Fail-closed, same rule as the Quality Gate: a mute that happened with
  // no durable record of the intent is precisely the untraceable silence
  // this route exists to prevent.
  if (!intent.persisted) {
    throw new ConsoleApiError(503, "audit_unavailable", {
      upstreamCode: "audit_intent_not_durable",
    });
  }

  const response = await consoleApiCall(`reminders/${path}`, "POST", body);
  if (response.ok) {
    await AdministrativeAudit.outcome(ctx, decision, "COMPLETED", {
      target,
      metadata,
    });
    return response;
  }

  const text = await response.text();
  await AdministrativeAudit.outcome(ctx, decision, "FAILED", {
    target,
    errorCode: `http_${response.status}`,
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
