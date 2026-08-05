/**
 * Typed HTTP access to the platform services this console owns screens
 * for. Mirrors the Next BFF's `lib/data-intelligence.ts` contract
 * (same headers, same base URLs) so both processes reach the services
 * identically during the strangler migration.
 */
import { Injectable } from '@nestjs/common';

import { getConfig } from '../config/config';

export interface UpstreamCall {
  readonly path: string;
  readonly method?: string;
  readonly body?: unknown;
  /** Server-derived operator attribution. Never a client value. */
  readonly actor?: string;
  readonly correlationId?: string | null;
  /**
   * Opt in to surfacing a structured upstream refusal.
   *
   * Off by default because an arbitrary upstream error body can echo a
   * service token or internal detail back to the browser. Turn it on
   * only where the refusal contract is known and the operator has to
   * see it — the Quality Gate is the case that forced this: Atlas
   * answers `409 {detail: {code: "override_required", ...}}`, and an
   * operator told only "upstream failed with 409" has no way to learn
   * that they must explicitly override the gate. Even then, only
   * `code` and `message` are carried across (see `UpstreamRefusal`);
   * the rest of the body is discarded.
   */
  readonly surfaceRefusal?: boolean;
}

/** The whitelisted shape of an upstream refusal. Nothing else crosses. */
export interface UpstreamRefusal {
  readonly code: string;
  readonly message: string;
}

export class UpstreamError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly refusal?: UpstreamRefusal,
  ) {
    super(message);
    this.name = 'UpstreamError';
  }
}

@Injectable()
export class UpstreamService {
  constructor(private readonly fetcher: typeof fetch = fetch) {}

  async explorer<T = unknown>(call: UpstreamCall): Promise<T> {
    const config = getConfig();
    if (!config.EXPLORER_OPS_TOKEN) {
      throw new Error('explorer_ops_token_missing');
    }
    return this.json<T>(
      `${trimSlash(config.EXPLORER_API_BASE_URL)}/explorer/${stripLeading(call.path)}`,
      call,
      {
        'X-Ops-Token': config.EXPLORER_OPS_TOKEN,
        ...(call.actor ? { 'X-Operator': call.actor } : {}),
        ...(call.correlationId ? { 'X-Request-Id': call.correlationId } : {}),
      },
    );
  }

  async atlas<T = unknown>(call: UpstreamCall): Promise<T> {
    const config = getConfig();
    if (!config.ATLAS_INTERNAL_TOKEN) {
      throw new Error('atlas_internal_token_missing');
    }
    return this.json<T>(
      `${trimSlash(config.ATLAS_API_BASE_URL)}/${stripLeading(call.path)}`,
      call,
      {
        'X-Internal-Token': config.ATLAS_INTERNAL_TOKEN,
        ...(call.actor ? { 'X-Operator': call.actor } : {}),
      },
    );
  }

  private async json<T>(
    url: string,
    call: UpstreamCall,
    headers: Record<string, string>,
  ): Promise<T> {
    const config = getConfig();
    const method = call.method ?? 'GET';
    const response = await this.fetcher(url, {
      method,
      signal: AbortSignal.timeout(config.UPSTREAM_TIMEOUT_MS),
      headers: {
        Accept: 'application/json',
        ...(call.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...headers,
      },
      body: call.body !== undefined ? JSON.stringify(call.body) : undefined,
    });
    if (!response.ok) {
      // Surface the status; the body may carry a service token echo in
      // pathological cases, so it is not included in the message.
      throw new UpstreamError(
        response.status,
        `upstream ${method} ${url} failed with ${response.status}`,
        call.surfaceRefusal ? await readRefusal(response) : undefined,
      );
    }
    return (await response.json()) as T;
  }
}

/**
 * Extract ONLY `code` and `message` from a FastAPI-style error body.
 *
 * Whitelist, not passthrough: whatever else the upstream put in the
 * body never reaches the caller. Returns undefined for any shape that
 * doesn't match, so a surprising body degrades to "no detail" rather
 * than leaking.
 */
async function readRefusal(
  response: Response,
): Promise<UpstreamRefusal | undefined> {
  let parsed: unknown;
  try {
    parsed = await response.json();
  } catch {
    return undefined;
  }
  const detail = (parsed as { detail?: unknown })?.detail;
  if (typeof detail !== 'object' || detail === null) {
    return undefined;
  }
  const { code, message } = detail as { code?: unknown; message?: unknown };
  if (typeof code !== 'string' || typeof message !== 'string') {
    return undefined;
  }
  return { code, message };
}

function trimSlash(value: string): string {
  return value.replace(/\/+$/, '');
}

function stripLeading(value: string): string {
  return value.replace(/^\/+/, '');
}
