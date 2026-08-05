/**
 * Session resolution cache.
 *
 * WHY THIS EXISTS
 * Every authenticated request through the Next.js BFF costs one
 * `GET /v1/operator/auth/me` round-trip to the Gateway
 * (`lib/session.ts`). The console has 14 client-side polling points —
 * the worst, `operational-command-center`, issues 8 requests every 10s
 * per open tab, each resolving the session again. In a Next process the
 * cache would be per-worker and short-lived; here it is shared and
 * long-lived.
 *
 * The Gateway stays the sole owner of identity. This never mints or
 * extends a session — it only remembers, briefly, what the Gateway just
 * said, and a short TTL bounds how stale a revocation can be.
 *
 * The raw session token is a credential: it is used to call the Gateway
 * and is otherwise never stored, keyed on, or logged. The cache key is
 * sha256(token), the same derivation the console already uses for
 * `OperatorContext.sessionId`.
 */
import { Injectable, Logger } from '@nestjs/common';
import { createHash } from 'node:crypto';

import { getConfig } from '../config/config';

export interface ResolvedSession {
  readonly operatorId: string;
  readonly operatorUsername: string | null;
  readonly role: string;
  readonly permissions: readonly string[];
  /** sha256(token) — safe to log, safe to use as a key. */
  readonly sessionId: string;
}

interface CacheEntry {
  readonly expiresAt: number;
  readonly session: ResolvedSession;
}

export type Fetcher = typeof fetch;

@Injectable()
export class SessionCacheService {
  private readonly logger = new Logger(SessionCacheService.name);
  private readonly store = new Map<string, CacheEntry>();

  constructor(
    private readonly fetcher: Fetcher = fetch,
    private readonly now: () => number = () => Date.now(),
  ) {}

  static sessionKey(token: string): string {
    return createHash('sha256').update(token).digest('hex');
  }

  get size(): number {
    return this.store.size;
  }

  /**
   * Resolve a session token to an operator, using the cache when fresh.
   * Returns null when the Gateway rejects the token or is unreachable —
   * an unresolvable session must never be treated as authenticated.
   */
  async resolve(token: string): Promise<ResolvedSession | null> {
    if (!token) return null;
    const key = SessionCacheService.sessionKey(token);
    const config = getConfig();

    const hit = this.store.get(key);
    if (hit && hit.expiresAt > this.now()) {
      // LRU touch: re-inserting moves the key to the end of Map order.
      this.store.delete(key);
      this.store.set(key, hit);
      return hit.session;
    }
    if (hit) {
      this.store.delete(key);
    }

    const session = await this.fetchFromGateway(token, key);
    if (session === null) {
      return null;
    }

    this.store.set(key, {
      expiresAt: this.now() + config.SESSION_CACHE_TTL_SECONDS * 1000,
      session,
    });
    this.evictOverflow(config.SESSION_CACHE_MAX_ENTRIES);
    return session;
  }

  /**
   * Drop a cached session. Called on logout so a signed-out operator
   * can't keep working off a cached entry for the rest of the TTL.
   */
  invalidate(token: string): void {
    this.store.delete(SessionCacheService.sessionKey(token));
  }

  clear(): void {
    this.store.clear();
  }

  private async fetchFromGateway(
    token: string,
    key: string,
  ): Promise<ResolvedSession | null> {
    const config = getConfig();
    try {
      const response = await this.fetcher(
        `${config.ROBOZAO_GATEWAY_URL.replace(/\/+$/, '')}/v1/operator/auth/me`,
        {
          method: 'GET',
          headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
          signal: AbortSignal.timeout(config.UPSTREAM_TIMEOUT_MS),
        },
      );
      if (!response.ok) {
        return null;
      }
      const body = (await response.json()) as Record<string, unknown>;
      const operatorId = body.id ?? body.operator_id;
      if (typeof operatorId !== 'string' || operatorId.length === 0) {
        this.logger.warn('gateway session response missing operator id');
        return null;
      }
      return {
        operatorId,
        operatorUsername:
          typeof body.username === 'string' ? body.username : null,
        role: typeof body.role === 'string' ? body.role : '',
        permissions: Array.isArray(body.permissions)
          ? body.permissions.filter((p): p is string => typeof p === 'string')
          : [],
        sessionId: key,
      };
    } catch (error) {
      // Never cache a failure — an outage must not pin every operator
      // out for the TTL, and must not be mistaken for a rejected token
      // by the caller either way (both yield null, which is deny).
      this.logger.warn(
        `gateway session resolution failed: ${
          error instanceof Error ? error.message : 'unknown'
        }`,
      );
      return null;
    }
  }

  private evictOverflow(max: number): void {
    while (this.store.size > max) {
      const oldest = this.store.keys().next();
      if (oldest.done) return;
      this.store.delete(oldest.value);
    }
  }
}
