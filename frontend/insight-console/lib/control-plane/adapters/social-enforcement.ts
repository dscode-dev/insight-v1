// Social Enforcement adapter (CONSOLE-SOCIAL-B). SERVER-ONLY.
//
// Typed, action-specific administrative COMMANDS over the Gateway's operator
// command plane (/v1/console/social/{users,posts,comments,agents,reports}/…).
// There is NO generic mutate/execute method. The browser never reaches this;
// it runs in the BFF, forwards the verified operator session (adminFetch adds
// X-Console-Service-Token + Bearer), and the command payload NEVER carries actor
// identity — operator identity is derived server-side by the Gateway. Errors are
// normalized into the canonical control-plane distinctions (no optimistic UI).

import { adminFetch, ConsoleApiError } from "@/lib/admin-api";
import { ControlPlaneError } from "@/lib/control-plane/errors";
import { observe } from "@/lib/control-plane/observability";

export interface EnforcementContext {
  readonly operatorToken?: string | null;
  readonly correlationId?: string | null;
}

/** The ONLY fields a command payload may carry. Actor identity is intentionally
 *  absent — the Gateway derives the operator from the verified session. */
export interface CommandInput {
  readonly reason: string;
  readonly report_id?: string;
  readonly suspend_days?: number;
}

export interface CommandResult {
  readonly ok: boolean;
  readonly capability: string;
  readonly correlation_id: string;
  readonly target: { type: string; id: string };
  readonly resulting_state?: string;
  readonly expires_at?: string;
}

const TIMEOUT_MS = 8000;

function codeFor(status: number): ControlPlaneError["code"] {
  if (status === 401) return "UNAUTHORIZED";
  if (status === 403) return "FORBIDDEN";
  if (status === 404) return "NOT_FOUND";
  if (status === 400) return "BAD_REQUEST";
  if (status === 409) return "CONFLICT";
  if (status === 501) return "CAPABILITY_UNSUPPORTED";
  if (status === 503) return "SERVICE_UNAVAILABLE";
  if (status === 504) return "TIMEOUT";
  return "UPSTREAM_ERROR";
}

/** sanitize keeps ONLY the allowed command fields — a structural strip of any
 *  actor/attribution field a caller might try to smuggle in. */
function sanitize(input: CommandInput): CommandInput {
  const reason = String(input.reason ?? "").trim();
  const out: { reason: string; report_id?: string; suspend_days?: number } = { reason };
  if (input.report_id) out.report_id = String(input.report_id);
  if (typeof input.suspend_days === "number" && input.suspend_days > 0) {
    out.suspend_days = Math.floor(input.suspend_days);
  }
  return out;
}

async function command(
  path: string,
  operation: string,
  input: CommandInput,
  ctx: EnforcementContext,
): Promise<CommandResult> {
  observe("adapter_request_started", { service: "social", operation, correlationId: ctx.correlationId ?? undefined });
  let res: Response;
  try {
    res = await adminFetch(`/v1/console/social/${path}`, {
      method: "POST",
      body: sanitize(input),
      operatorToken: ctx.operatorToken ?? undefined,
      correlationId: ctx.correlationId ?? undefined,
      timeoutMs: TIMEOUT_MS,
    });
  } catch (err) {
    const status = err instanceof ConsoleApiError ? err.status : 502;
    observe("adapter_request_failed", { service: "social", operation, code: String(status), correlationId: ctx.correlationId ?? undefined });
    throw new ControlPlaneError(codeFor(status), "enforcement command unreachable", {
      service: "social", operation, correlationId: ctx.correlationId ?? undefined,
    });
  }
  if (!res.ok) {
    observe("adapter_request_failed", { service: "social", operation, code: String(res.status), correlationId: ctx.correlationId ?? undefined });
    let detail = `enforcement ${operation} failed`;
    try {
      const b = (await res.json()) as { detail?: string };
      if (b?.detail) detail = b.detail;
    } catch { /* ignore */ }
    throw new ControlPlaneError(codeFor(res.status), detail, {
      service: "social", operation, correlationId: ctx.correlationId ?? undefined,
    });
  }
  observe("adapter_request_completed", { service: "social", operation, correlationId: ctx.correlationId ?? undefined });
  return (await res.json()) as CommandResult;
}

function uid(id: string): string {
  return encodeURIComponent(id);
}

export interface EnforcementState {
  readonly target: { type: string; id: string };
  readonly state: string;
  readonly expires_at?: string;
  readonly history: Array<{
    action: string;
    operator_id: string;
    note: string;
    occurred_at: string;
    report_id?: string;
  }>;
}

/** Read the current enforcement state + action history for a target (read model
 *  used by the intervention UI — real state, never a decorative flag). */
export async function enforcementState(
  ctx: EnforcementContext,
  targetType: string,
  id: string,
): Promise<EnforcementState> {
  const operation = "enforcement.state";
  observe("adapter_request_started", { service: "social", operation, correlationId: ctx.correlationId ?? undefined });
  let res: Response;
  try {
    res = await adminFetch(`/v1/console/social/enforcement/${encodeURIComponent(targetType)}/${uid(id)}`, {
      operatorToken: ctx.operatorToken ?? undefined,
      correlationId: ctx.correlationId ?? undefined,
      timeoutMs: TIMEOUT_MS,
    });
  } catch (err) {
    const status = err instanceof ConsoleApiError ? err.status : 502;
    throw new ControlPlaneError(codeFor(status), "enforcement state unreachable", {
      service: "social", operation, correlationId: ctx.correlationId ?? undefined,
    });
  }
  if (!res.ok) {
    throw new ControlPlaneError(codeFor(res.status), `enforcement ${operation} failed`, {
      service: "social", operation, correlationId: ctx.correlationId ?? undefined,
    });
  }
  observe("adapter_request_completed", { service: "social", operation, correlationId: ctx.correlationId ?? undefined });
  return (await res.json()) as EnforcementState;
}

export const SocialEnforcement = {
  // USER
  suspendUser: (ctx: EnforcementContext, id: string, input: CommandInput) =>
    command(`users/${uid(id)}/suspend`, "user.suspend", input, ctx),
  unsuspendUser: (ctx: EnforcementContext, id: string, input: CommandInput) =>
    command(`users/${uid(id)}/unsuspend`, "user.unsuspend", input, ctx),
  banUser: (ctx: EnforcementContext, id: string, input: CommandInput) =>
    command(`users/${uid(id)}/ban`, "user.ban", input, ctx),
  unbanUser: (ctx: EnforcementContext, id: string, input: CommandInput) =>
    command(`users/${uid(id)}/unban`, "user.unban", input, ctx),
  // CONTENT
  hidePost: (ctx: EnforcementContext, id: string, input: CommandInput) =>
    command(`posts/${uid(id)}/hide`, "post.hide", input, ctx),
  restorePost: (ctx: EnforcementContext, id: string, input: CommandInput) =>
    command(`posts/${uid(id)}/restore`, "post.restore", input, ctx),
  hideComment: (ctx: EnforcementContext, id: string, input: CommandInput) =>
    command(`comments/${uid(id)}/hide`, "comment.hide", input, ctx),
  restoreComment: (ctx: EnforcementContext, id: string, input: CommandInput) =>
    command(`comments/${uid(id)}/restore`, "comment.restore", input, ctx),
  // AGENT
  deactivateAgent: (ctx: EnforcementContext, id: string, input: CommandInput) =>
    command(`agents/${uid(id)}/deactivate`, "agent.deactivate", input, ctx),
  reactivateAgent: (ctx: EnforcementContext, id: string, input: CommandInput) =>
    command(`agents/${uid(id)}/reactivate`, "agent.reactivate", input, ctx),
  // REPORT
  reviewReport: (ctx: EnforcementContext, id: string, input: CommandInput) =>
    command(`reports/${uid(id)}/review`, "report.review", input, ctx),
  resolveReport: (ctx: EnforcementContext, id: string, input: CommandInput) =>
    command(`reports/${uid(id)}/resolve`, "report.resolve", input, ctx),
  dismissReport: (ctx: EnforcementContext, id: string, input: CommandInput) =>
    command(`reports/${uid(id)}/dismiss`, "report.dismiss", input, ctx),
};

// Regression guard (privacy/impersonation): this adapter exposes ONLY typed
// commands and no generic mutate/execute/proxy. Enforced by tests.
