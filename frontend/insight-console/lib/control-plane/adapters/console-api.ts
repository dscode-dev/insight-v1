// Console backend (insight-console-api) adapter. SERVER-ONLY.
//
// The Nest service owns session caching, realtime SSE fan-out, and the
// console domains being strangled out of this BFF. It never mints
// identity — the Gateway does, this BFF resolves it, and we hand the
// already-resolved OperatorContext across as an HMAC-signed envelope.
//
// WHY SIGNED: without a signature, anything able to reach the Nest port
// could assert any operator, which would break the console's core rule
// that identity is server-derived and never caller-asserted (see
// `assertNoClientActor` in security/operator-context.ts). The signature
// proves the identity came from this process.

import { createHmac } from "node:crypto";

import type { OperatorContext } from "@/lib/control-plane/security/operator-context";

const CONSOLE_API_BASE_URL =
  process.env.CONSOLE_API_BASE_URL ?? "http://insight-console-api:3002";
const CONSOLE_API_SIGNING_SECRET = process.env.CONSOLE_API_SIGNING_SECRET ?? "";

export const IDENTITY_HEADER = "x-console-identity";
export const IDENTITY_SIGNATURE_HEADER = "x-console-identity-signature";

export class ConsoleApiUnconfiguredError extends Error {
  constructor() {
    super("console_api_signing_secret_missing");
  }
}

/** Build the signed headers carrying `operator` to the console backend. */
export function identityHeaders(
  operator: OperatorContext,
): Record<string, string> {
  if (!CONSOLE_API_SIGNING_SECRET) {
    throw new ConsoleApiUnconfiguredError();
  }
  const identity = {
    operatorId: operator.operatorId,
    operatorUsername: operator.operatorUsername,
    identityId: operator.identityId,
    identityKind: operator.identityKind,
    permissions: operator.permissions ?? [],
    // OperatorContext carries `roles` (plural); the backend envelope
    // keeps a single canonical role string for logging/attribution.
    role: operator.roles?.[0] ?? "",
    sessionId: operator.sessionId,
    correlationId: operator.correlationId ?? null,
    // Verified against a 60s window on the other side — bounds replay
    // if an envelope ever lands in a log.
    issuedAt: Math.floor(Date.now() / 1000),
  };
  const envelope = Buffer.from(JSON.stringify(identity), "utf8").toString(
    "base64url",
  );
  const signature = createHmac("sha256", CONSOLE_API_SIGNING_SECRET)
    .update(envelope)
    .digest("hex");
  return {
    [IDENTITY_HEADER]: envelope,
    [IDENTITY_SIGNATURE_HEADER]: signature,
  };
}

/** JSON call against the console backend, carrying signed identity. */
export async function consoleApiCall(
  operator: OperatorContext,
  path: string,
  method: string = "GET",
  body?: unknown,
): Promise<Response> {
  let headers: Record<string, string>;
  try {
    headers = identityHeaders(operator);
  } catch {
    return Response.json(
      { detail: "console_api_signing_secret_missing" },
      { status: 503 },
    );
  }

  const upstream = await fetch(
    `${CONSOLE_API_BASE_URL.replace(/\/+$/, "")}/${path.replace(/^\/+/, "")}`,
    {
      method,
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
      headers: {
        Accept: "application/json",
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...headers,
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    },
  );
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
 * Pipe an SSE stream from the console backend to the browser.
 *
 * The Next server is `output: "standalone"` (a real Node process), so
 * holding this connection open is fine. Streaming through the BFF keeps
 * the browser on one origin, so the session cookie and CSP are unchanged
 * and no edge-proxy reconfiguration is needed to adopt realtime.
 */
export async function consoleApiStream(
  operator: OperatorContext,
  channel: string,
  signal: AbortSignal,
): Promise<Response> {
  let headers: Record<string, string>;
  try {
    headers = identityHeaders(operator);
  } catch {
    return Response.json(
      { detail: "console_api_signing_secret_missing" },
      { status: 503 },
    );
  }

  const upstream = await fetch(
    `${CONSOLE_API_BASE_URL.replace(/\/+$/, "")}/realtime/channels/${encodeURIComponent(channel)}`,
    {
      method: "GET",
      cache: "no-store",
      // Deliberately NO timeout: an SSE stream is meant to stay open.
      // The caller's abort signal (client disconnect) is what ends it.
      signal,
      headers: { Accept: "text/event-stream", ...headers },
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
