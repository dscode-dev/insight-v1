// Insight Control Plane adapter. SERVER-ONLY.
//
// Per insight-context.md v2.0 the Control Plane is the administrative
// authority for the Intelligence plane — it authenticates operators,
// owns their sessions and RBAC, carries the audit spine, and is the one
// service the Console talks to. Everything else (Explorer, Atlas,
// Nexus, the Node Agent) is reached THROUGH it.
//
// WHAT REPLACED WHAT. This adapter used to sign an HMAC envelope
// describing an operator the Console had already resolved against the
// Gateway. That inverted the authority: the Console decided who you
// were and the backend believed it. Now the Console forwards the opaque
// session token from its HttpOnly cookie and the Control Plane decides
// — which also removes a round-trip, since resolving an identity purely
// in order to sign it is no longer necessary.
//
// It also drops a `node:crypto` import from this module. `session.ts`
// imports it, and Next's bundler follows that chain: the HMAC helper
// made `next build` fail with UnhandledSchemeError on "node:crypto".

import { readSessionCookie } from "@/lib/session-cookie";

/**
 * Read at CALL time, not module load.
 *
 * A module-level capture is invisible to anything that sets the
 * variable afterwards, which makes this module untestable and makes a
 * config change depend on process restart order rather than on config.
 */
function baseUrl(): string {
  return (
    process.env.CONSOLE_API_BASE_URL ?? "http://insight-console-api:3002"
  ).replace(/\/+$/, "");
}

function url(path: string): string {
  return `${baseUrl()}/${path.replace(/^\/+/, "")}`;
}

/**
 * Call the Control Plane with an explicit session token.
 *
 * Takes a raw token rather than an OperatorContext because the two
 * callers that need it — login and session resolution — run before any
 * operator has been resolved.
 */
export async function controlPlaneFetch(
  path: string,
  init: {
    method?: string;
    body?: unknown;
    token?: string | null;
    timeoutMs?: number;
    /**
     * Forwarded to the upstream service that enforces idempotency.
     *
     * The Node Agent keys command creation on it: a retry without the key
     * creates a second command instead of returning the first, which for an
     * approved operation means running it twice.
     */
    idempotencyKey?: string;
  } = {},
): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (init.token) {
    headers.Authorization = `Bearer ${init.token}`;
  }
  if (init.idempotencyKey) {
    headers["Idempotency-Key"] = init.idempotencyKey;
  }
  return fetch(url(path), {
    method: init.method ?? "GET",
    cache: "no-store",
    signal: AbortSignal.timeout(init.timeoutMs ?? 10_000),
    headers,
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
  });
}

/**
 * JSON call against the Control Plane on behalf of the signed-in
 * operator. Reads the session cookie itself: the token is a credential
 * and threading it through every call site only widens its exposure.
 */
export async function consoleApiCall(
  path: string,
  method: string = "GET",
  body?: unknown,
): Promise<Response> {
  const token = readSessionCookie();
  if (!token) {
    // No cookie means no session. Answering 401 here keeps the failure
    // shaped like an auth problem rather than an upstream one.
    return Response.json({ detail: "unauthenticated" }, { status: 401 });
  }

  const upstream = await controlPlaneFetch(path, { method, body, token });
  const text = await upstream.text();
  return new Response(text, {
    status: upstream.status,
    headers: {
      "content-type":
        upstream.headers.get("content-type") ?? "application/json",
      "cache-control": "no-store",
    },
  });
}

/**
 * Pipe an SSE stream from the Control Plane to the browser.
 *
 * The Next server is `output: "standalone"` (a real Node process), so
 * holding this connection open is fine. Streaming through the Console
 * keeps the browser on one origin, so the session cookie and CSP are
 * unchanged and no edge-proxy reconfiguration is needed.
 */
export async function consoleApiStream(
  channel: string,
  signal: AbortSignal,
): Promise<Response> {
  const token = readSessionCookie();
  if (!token) {
    return Response.json({ detail: "unauthenticated" }, { status: 401 });
  }

  const upstream = await fetch(
    url(`realtime/channels/${encodeURIComponent(channel)}`),
    {
      method: "GET",
      cache: "no-store",
      // Deliberately NO timeout: an SSE stream is meant to stay open.
      // The caller's abort signal (client disconnect) is what ends it.
      signal,
      headers: {
        Accept: "text/event-stream",
        Authorization: `Bearer ${token}`,
      },
    },
  );

  if (!upstream.ok || upstream.body === null) {
    return Response.json(
      { detail: "console_api_stream_unavailable" },
      { status: upstream.status === 200 ? 502 : upstream.status },
    );
  }

  return new Response(upstream.body, {
    status: 200,
    headers: {
      "content-type": "text/event-stream",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
      "x-accel-buffering": "no",
    },
  });
}
