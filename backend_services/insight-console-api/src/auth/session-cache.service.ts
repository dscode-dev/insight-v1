/**
 * Session resolution cache.
 *
 * WHY THIS EXISTS
 * Every authenticated request the console makes has to resolve the
 * operator session. The console has 14 client-side polling points — the
 * worst, `operational-command-center`, issues 8 requests every 10s per
 * open tab — so an uncached resolution is a database round-trip per
 * request, per tab.
 *
 * WHAT CHANGED
 * This used to ask the Gateway (`GET /v1/operator/auth/me`) who the
 * operator was. insight-context.md v2.0 puts administrative identity on
 * the Control Plane and states the Gateway is not responsible for
 * operators, so the lookup now goes to this service's own
 * `control_plane` schema. It is no longer a cache in front of somebody
 * else's authority — it is a cache in front of ours.
 *
 * The TTL still matters, and for a sharper reason than before: a
 * revoked session or a deactivated operator stays usable until the
 * entry expires. `OperatorRepository.resolveSession` enforces
 * revocation, expiry and the active flag in SQL, so the cache TTL is
 * the ONLY window where those can be stale. Keep it short.
 *
 * The raw token is a credential: never stored, never keyed on, never
 * logged. The key is sha256(token), the same derivation the console
 * uses for `OperatorContext.sessionId`.
 */
import { createHash } from 'node:crypto';

import { Injectable, Logger } from '@nestjs/common';

import { getConfig } from '../config/config';
import type {
  OperatorRepository,
  ResolvedSession,
} from '../identity/operator.repository';

export type { ResolvedSession } from '../identity/operator.repository';

interface CacheEntry {
  readonly expiresAt: number;
  readonly session: ResolvedSession;
}

@Injectable()
export class SessionCacheService {
  private readonly logger = new Logger(SessionCacheService.name);
  private readonly store = new Map<string, CacheEntry>();

  constructor(
    private readonly operators: OperatorRepository,
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
   * Returns null when the session is unknown, expired, revoked, or its
   * operator is deactivated — an unresolvable session is never treated
   * as authenticated.
   */
  async resolve(token: string): Promise<ResolvedSession | null> {
    if (!token) return null;
    const key = SessionCacheService.sessionKey(token);
    const config = getConfig();

    const cached = this.store.get(key);
    if (cached !== undefined && cached.expiresAt > this.now()) {
      // Touch for LRU: re-inserting moves it to the end of the Map's
      // insertion order, which is what the eviction below relies on.
      this.store.delete(key);
      this.store.set(key, cached);
      return cached.session;
    }
    this.store.delete(key);

    let session: ResolvedSession | null;
    try {
      session = await this.operators.resolveSession(token);
    } catch (error) {
      // A database outage must NOT be cached: caching a failure would
      // lock every operator out for the whole TTL even after Postgres
      // recovers.
      this.logger.warn(
        `session resolution failed: ${
          error instanceof Error ? error.message : 'unknown error'
        }`,
      );
      return null;
    }
    if (session === null) {
      // Also not cached: a rejected token is cheap to re-check, and
      // caching it would keep rejecting a session that was just
      // re-issued for the same value.
      return null;
    }

    this.store.set(key, {
      expiresAt: this.now() + config.SESSION_CACHE_TTL_SECONDS * 1000,
      session,
    });
    this.evictIfNeeded(config.SESSION_CACHE_MAX_ENTRIES);
    return session;
  }

  /**
   * Drop a cached entry. Called on logout so the operator stops being
   * authenticated immediately rather than at the end of the TTL.
   */
  invalidate(token: string): void {
    if (!token) return;
    this.store.delete(SessionCacheService.sessionKey(token));
  }

  /** Drop everything. Used when an operator is deactivated. */
  invalidateAll(): void {
    this.store.clear();
  }

  private evictIfNeeded(max: number): void {
    while (this.store.size > max) {
      const oldest = this.store.keys().next();
      if (oldest.done === true) return;
      this.store.delete(oldest.value);
    }
  }
}
