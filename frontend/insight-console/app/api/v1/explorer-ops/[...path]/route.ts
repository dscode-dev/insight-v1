// /api/v1/explorer-ops/* — Explorer curation, jobs, quality and runtime,
// via insight-console-api.
//
// The Explorer audit found 33 endpoints with no console consumer at
// all. This route opens the four groups with real operational
// consequence. Reads take the ordinary read permission; writes are
// classified by `classifyExplorerOpsWrite`, which DEFAULT-DENIES
// anything it does not recognise — so a new Explorer mutation cannot
// become reachable through this proxy, unaudited, just by existing
// upstream.
//
// Governed writes take the same spine as moderation/actions and the
// Quality Gate: capability → authorize → audit(intent, fail-closed) →
// mutate → audit(outcome).

import { ConsoleApiError } from "@/lib/admin-api";
import { requireOperator, requirePermission, withApiHandler } from "@/lib/api-guard";
import { consoleApiCall } from "@/lib/control-plane/adapters/console-api";
import { classifyExplorerOpsWrite } from "@/lib/control-plane/explorer-ops-routing";
import {
  AdministrativeAudit,
  assertNoClientActor,
  authorize,
  observeSecurity,
  operatorContextFromOperator,
} from "@/lib/control-plane/security";

const WRITE_PERMISSION = "config.write" as const;

function pathOf(req: Request): { path: string; search: string } {
  const url = new URL(req.url);
  const marker = "/explorer-ops/";
  return {
    path: decodeURIComponent(url.pathname.split(marker)[1] ?? ""),
    search: url.search || "",
  };
}

export const GET = withApiHandler(async (req) => {
  await requirePermission("config.read");
  const operator = await requireOperator();
  const { path, search } = pathOf(req);
  return consoleApiCall(`explorer-ops/${path}${search}`);
});

export const POST = withApiHandler(async (req) => {
  const operator = await requireOperator();
  const ctx = operatorContextFromOperator(operator, req);
  const { path } = pathOf(req);

  let body: Record<string, unknown>;
  try {
    body = (await req.json()) as Record<string, unknown>;
  } catch {
    // Several Explorer controls legitimately take no body.
    body = {};
  }
  assertNoClientActor(body);

  const route = classifyExplorerOpsWrite(path);
  if (route.kind === "refuse") {
    throw new ConsoleApiError(400, route.reason);
  }

  await requirePermission(WRITE_PERMISSION);

  if (route.kind === "ordinary") {
    // Operational steering — re-running or pausing work, not deciding
    // what is true. Explorer keeps its own audit entry for these.
    return consoleApiCall(`explorer-ops/${path}`, "POST", body);
  }

  const target = {
    environmentId: "google-cloud",
    serviceId: "explorer",
    resourceType: route.resourceType,
    resourceId:
      typeof body.external_id === "string" ? body.external_id : null,
  };
  const metadata = {
    action: path,
    // Recorded because promotion appends the envelope to the VALIDATED
    // lake layer that Atlas's StrengthSyncWatcher consumes — the blast
    // radius of a curation decision reaches Atlas's team ratings.
    competition: typeof body.competition === "string" ? body.competition : null,
  };

  const decision = authorize(ctx, route.capability, WRITE_PERMISSION, target);
  const intent = await AdministrativeAudit.decision(ctx, decision, {
    target,
    metadata,
  });
  if (!decision.allowed) {
    observeSecurity("authorization_denied", {
      operatorId: ctx.operatorId,
      capability: route.capability,
      reasonCode: decision.reasonCode,
      correlationId: ctx.correlationId,
    });
    throw new ConsoleApiError(403, "permission_denied", {
      upstreamCode: WRITE_PERMISSION,
    });
  }
  observeSecurity("authorization_allowed", {
    operatorId: ctx.operatorId,
    capability: route.capability,
    correlationId: ctx.correlationId,
  });
  if (!intent.persisted) {
    throw new ConsoleApiError(503, "audit_unavailable", {
      upstreamCode: "audit_intent_not_durable",
    });
  }

  const response = await consoleApiCall(`explorer-ops/${path}`, "POST", body);
  await AdministrativeAudit.outcome(
    ctx,
    decision,
    response.ok ? "COMPLETED" : "FAILED",
    {
      target,
      metadata,
      ...(response.ok
        ? {}
        : {
            errorCode: `http_${response.status}`,
            retryable: response.status >= 500,
          }),
    },
  );
  return response;
});
