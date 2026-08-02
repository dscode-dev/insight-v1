// Social Enforcement command BFF helper (CONSOLE-SOCIAL-B). SERVER-ONLY.
//
// Mirrors socialRead but for the ONLY mutating console surface. Every command
// route: resolve OperatorContext (verified session) → authorize the EXACT
// capability's permission (real decision; registry presence never grants;
// fail-closed) → parse a minimal body (reason mandatory; NO actor fields) → call
// the typed enforcement adapter → normalize canonical errors. Operator identity
// is NEVER taken from the body; it is derived from the session by the Gateway.

import { ConsoleApiError } from "@/lib/admin-api";
import { withApiHandler } from "@/lib/api-guard";
import { readSessionCookie } from "@/lib/session";
import { resolveOperatorContext } from "@/lib/control-plane/security/operator-context";
import { authorize } from "@/lib/control-plane/security/authorization";
import { observeSecurity } from "@/lib/control-plane/security/observability";
import { ControlPlaneError } from "@/lib/control-plane/errors";
import type { CommandInput, EnforcementContext, CommandResult } from "@/lib/control-plane/adapters/social-enforcement";
import type { Permission } from "@/types/auth";
import { robozaoOperationCommand } from "@/lib/robozao";

/** Path segment counting from the end (0 = last). `/users/{id}/suspend` → id at 1. */
export function segmentFromEnd(url: string, n: number): string {
  const parts = new URL(url).pathname.split("/").filter(Boolean);
  return decodeURIComponent(parts[parts.length - 1 - n] ?? "");
}

/** Parse + validate the command body. Reason is mandatory; actor fields (if any
 *  client tried to send them) are simply not read — a structural strip. */
async function parseBody(req: Request): Promise<CommandInput> {
  let raw: unknown = {};
  try {
    const text = await req.text();
    if (text) raw = JSON.parse(text);
  } catch {
    throw new ConsoleApiError(400, "invalid_json");
  }
  const b = (raw ?? {}) as Record<string, unknown>;
  const reason = typeof b.reason === "string" ? b.reason.trim() : "";
  if (!reason || reason.length > 512) {
    throw new ConsoleApiError(400, "reason_required");
  }
  const input: CommandInput = { reason };
  if (typeof b.report_id === "string" && b.report_id) {
    (input as { report_id?: string }).report_id = b.report_id;
  }
  if (typeof b.suspend_days === "number" && b.suspend_days > 0) {
    (input as { suspend_days?: number }).suspend_days = Math.floor(b.suspend_days);
  }
  return input;
}

export function socialCommand(
  capability: string,
  permission: Permission,
  run: (id: string, input: CommandInput, ctx: EnforcementContext) => Promise<CommandResult>,
): (req: Request) => Promise<Response> {
  return withApiHandler(async (req) => {
    const operator = await resolveOperatorContext(req);
    const decision = authorize(operator, capability, permission);
    if (!decision.allowed) {
      observeSecurity("authorization_denied", {
        operatorId: operator.operatorId,
        capability,
        reasonCode: decision.reasonCode,
        correlationId: operator.correlationId,
      });
      throw new ConsoleApiError(403, "permission_denied", { upstreamCode: permission });
    }
    const id = segmentFromEnd(req.url, 1); // `.../{id}/{action}`
    const input = await parseBody(req);
    const ctx: EnforcementContext = {
      operatorToken: readSessionCookie(),
      correlationId: operator.correlationId,
    };
    try {
      const data = await run(id, input, ctx);
      return Response.json(data, { headers: { "cache-control": "no-store" } });
    } catch (e) {
      if (e instanceof ControlPlaneError) {
        throw new ConsoleApiError(e.httpStatus, e.code, { upstreamCode: e.code });
      }
      throw e;
    }
  });
}

export function governedSocialCommand(
  actionId: "social.agent.deactivate" | "social.agent.reactivate" | "social.content.hide" | "social.content.restore",
  permission: Permission,
  target: "agent" | "post" | "comment",
): (req: Request) => Promise<Response> {
  return withApiHandler(async (req) => {
    const operator = await resolveOperatorContext(req);
    const decision = authorize(operator, actionId, permission);
    if (!decision.allowed) {
      throw new ConsoleApiError(403, "permission_denied", { upstreamCode: permission });
    }
    const id = segmentFromEnd(req.url, 1);
    const input = await parseBody(req);
    const payload = target === "agent"
      ? { agent_id: id, reason: input.reason }
      : { content_id: id, content_type: target, reason: input.reason };
    const result = await robozaoOperationCommand(
      { action_id: actionId, payload },
      req.headers.get("idempotency-key") ??
        `${actionId}:${id}:${operator.correlationId}`,
      operator.correlationId ?? "",
    );
    return Response.json(
      { operation: result.payload, idempotent_replay: result.replay },
      { status: result.status, headers: { "cache-control": "no-store" } },
    );
  });
}
