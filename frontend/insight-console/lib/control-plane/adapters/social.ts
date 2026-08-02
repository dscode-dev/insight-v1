// Social Control Plane adapter (CONSOLE-SOCIAL-A1). SERVER-ONLY.
//
// Read-only, capability-oriented readers over the Gateway's operator-authed
// Social read plane (/v1/console/social/*). The browser NEVER reaches Social;
// this runs in the BFF, forwards the verified operator session (via adminFetch),
// normalizes errors into the canonical control-plane distinctions, and caps
// payloads. Not a god adapter — small readers grouped by resource.

import { adminFetch, ConsoleApiError } from "@/lib/admin-api";
import { ControlPlaneError } from "@/lib/control-plane/errors";
import { observe } from "@/lib/control-plane/observability";

export interface SocialReadContext {
  readonly operatorToken?: string | null;
  readonly correlationId?: string | null;
}

const TIMEOUT_MS = 6000;

function codeFor(status: number): ControlPlaneError["code"] {
  if (status === 401) return "UNAUTHORIZED";
  if (status === 403) return "FORBIDDEN";
  if (status === 404) return "NOT_FOUND";
  if (status === 400) return "BAD_REQUEST";
  if (status === 501) return "CAPABILITY_UNSUPPORTED";
  if (status === 503) return "SERVICE_UNAVAILABLE";
  if (status === 504) return "TIMEOUT";
  return "UPSTREAM_ERROR";
}

async function socialGet<T>(path: string, operation: string, ctx: SocialReadContext): Promise<T> {
  observe("adapter_request_started", { service: "social", operation, correlationId: ctx.correlationId ?? undefined });
  let res: Response;
  try {
    res = await adminFetch(`/v1/console/social/${path}`, {
      operatorToken: ctx.operatorToken ?? undefined,
      correlationId: ctx.correlationId ?? undefined,
      timeoutMs: TIMEOUT_MS,
    });
  } catch (err) {
    // adminFetch throws ConsoleApiError(502/504) on transport failure.
    const status = err instanceof ConsoleApiError ? err.status : 502;
    observe("adapter_request_failed", { service: "social", operation, code: String(status), correlationId: ctx.correlationId ?? undefined });
    throw new ControlPlaneError(codeFor(status), "social read plane unreachable", {
      service: "social",
      operation,
      correlationId: ctx.correlationId ?? undefined,
    });
  }
  if (!res.ok) {
    observe("adapter_request_failed", { service: "social", operation, code: String(res.status), correlationId: ctx.correlationId ?? undefined });
    throw new ControlPlaneError(codeFor(res.status), `social ${operation} failed`, {
      service: "social",
      operation,
      correlationId: ctx.correlationId ?? undefined,
    });
  }
  observe("adapter_request_completed", { service: "social", operation, correlationId: ctx.correlationId ?? undefined });
  return (await res.json()) as T;
}

function qs(params: Record<string, string | undefined>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") u.set(k, v);
  const s = u.toString();
  return s ? `?${s}` : "";
}

export interface SocialListQuery {
  limit?: string;
  cursor?: string;
  q?: string;
  author_type?: string;
  author_id?: string;
  boosted?: string;
  window?: string;
  kind?: string;
  post_id?: string;
  user_id?: string;
  status?: string;
  entity_type?: string;
  entity_id?: string;
}

export const SocialControlPlane = {
  overview(ctx: SocialReadContext, window?: string) {
    return socialGet<unknown>(`overview${qs({ window })}`, "social.overview.read", ctx);
  },
  activity(ctx: SocialReadContext, query: SocialListQuery = {}) {
    return socialGet<unknown>(`activity${qs({ limit: query.limit, cursor: query.cursor, kind: query.kind })}`, "social.activity.read", ctx);
  },
  listUsers(ctx: SocialReadContext, query: SocialListQuery = {}) {
    return socialGet<unknown>(`users${qs({ limit: query.limit, cursor: query.cursor, q: query.q })}`, "social.user.read", ctx);
  },
  getUser(ctx: SocialReadContext, id: string) {
    return socialGet<unknown>(`users/${encodeURIComponent(id)}`, "social.user.read", ctx);
  },
  listAgents(ctx: SocialReadContext, query: SocialListQuery = {}) {
    return socialGet<unknown>(`agents${qs({ limit: query.limit })}`, "social.agent.read", ctx);
  },
  getAgent(ctx: SocialReadContext, id: string) {
    return socialGet<unknown>(`agents/${encodeURIComponent(id)}`, "social.agent.read", ctx);
  },
  listPosts(ctx: SocialReadContext, query: SocialListQuery = {}) {
    return socialGet<unknown>(
      `posts${qs({ limit: query.limit, cursor: query.cursor, author_type: query.author_type, author_id: query.author_id, boosted: query.boosted })}`,
      "social.post.read",
      ctx,
    );
  },
  getPost(ctx: SocialReadContext, id: string) {
    return socialGet<unknown>(`posts/${encodeURIComponent(id)}`, "social.post.read", ctx);
  },
  // ---- CONSOLE-SOCIAL-A2 investigation plane ----
  listComments(ctx: SocialReadContext, query: SocialListQuery = {}) {
    return socialGet<unknown>(
      `comments${qs({ limit: query.limit, cursor: query.cursor, post_id: query.post_id, author_id: query.author_id, author_type: query.author_type })}`,
      "social.comment.read",
      ctx,
    );
  },
  getComment(ctx: SocialReadContext, id: string) {
    return socialGet<unknown>(`comments/${encodeURIComponent(id)}`, "social.comment.read", ctx);
  },
  listCommunities(ctx: SocialReadContext, query: SocialListQuery = {}) {
    return socialGet<unknown>(`communities${qs({ limit: query.limit })}`, "social.community.read", ctx);
  },
  getCommunity(ctx: SocialReadContext, id: string) {
    return socialGet<unknown>(`communities/${encodeURIComponent(id)}`, "social.community.read", ctx);
  },
  relationships(ctx: SocialReadContext, entityType: string, entityId: string) {
    return socialGet<unknown>(`relationships${qs({ entity_type: entityType, entity_id: entityId })}`, "social.relationship.read", ctx);
  },
  listBoosts(ctx: SocialReadContext, query: SocialListQuery = {}) {
    return socialGet<unknown>(
      `boosts${qs({ limit: query.limit, cursor: query.cursor, post_id: query.post_id, user_id: query.user_id, status: query.status })}`,
      "social.boost.read",
      ctx,
    );
  },
  timeline(ctx: SocialReadContext, entityType: string, entityId: string, limit?: string) {
    return socialGet<unknown>(`timeline${qs({ entity_type: entityType, entity_id: entityId, limit })}`, "social.investigation.read", ctx);
  },
};
