import { loadConfig, resetConfigForTests } from '../config/config';
import type {
  OperatorRepository,
  ResolvedSession,
} from '../identity/operator.repository';
import { SessionCacheService } from './session-cache.service';

const BASE_ENV = {
  CONTROL_PLANE_DATABASE_URL: 'postgres://u:p@postgres:5432/insight_db',
  ROBOZAO_GATEWAY_URL: 'http://robozao-gateway:8095',
  SESSION_CACHE_TTL_SECONDS: '30',
  SESSION_CACHE_MAX_ENTRIES: '3',
};

function session(id = 'op-1'): ResolvedSession {
  return {
    operator: {
      id,
      username: 'ana',
      email: 'ana@konoha.lab',
      displayName: 'Ana',
      role: 'SuperAdmin',
      permissions: ['console.access'],
      isActive: true,
    },
    sessionId: 'ignored-by-these-tests',
    expiresAt: new Date(Date.now() + 3_600_000),
  };
}

/** Repository stub recording how often the database was consulted. */
function repo(
  resolve: (token: string) => Promise<ResolvedSession | null>,
): { repo: OperatorRepository; calls: () => number } {
  let calls = 0;
  const stub = {
    resolveSession: async (token: string) => {
      calls += 1;
      return resolve(token);
    },
  } as unknown as OperatorRepository;
  return { repo: stub, calls: () => calls };
}

describe('SessionCacheService', () => {
  let clock: number;

  beforeEach(() => {
    clock = 1_000_000;
    resetConfigForTests();
    process.env = { ...process.env, ...BASE_ENV } as NodeJS.ProcessEnv;
    loadConfig(process.env);
  });

  afterEach(() => resetConfigForTests());

  const now = () => clock;

  it('resolves through the repository on a miss', async () => {
    const { repo: r, calls } = repo(async () => session());
    const cache = new SessionCacheService(r, now);

    const resolved = await cache.resolve('token-1');

    expect(calls()).toBe(1);
    expect(resolved?.operator.id).toBe('op-1');
    expect(resolved?.operator.permissions).toEqual(['console.access']);
  });

  it('serves a second request from cache without touching the database', async () => {
    const { repo: r, calls } = repo(async () => session());
    const cache = new SessionCacheService(r, now);

    await cache.resolve('token-1');
    await cache.resolve('token-1');

    // The entire point: 14 polling points × one resolution each would
    // otherwise be a query per request per open tab.
    expect(calls()).toBe(1);
  });

  it('re-resolves once the TTL expires', async () => {
    const { repo: r, calls } = repo(async () => session());
    const cache = new SessionCacheService(r, now);

    await cache.resolve('token-1');
    clock += 31_000; // TTL is 30s
    await cache.resolve('token-1');

    // This TTL is the ONLY staleness window for revocation, since
    // resolveSession enforces revoked/expired/inactive in SQL.
    expect(calls()).toBe(2);
  });

  it('keys on the token, not the operator', async () => {
    const { repo: r, calls } = repo(async () => session());
    const cache = new SessionCacheService(r, now);

    await cache.resolve('token-1');
    await cache.resolve('token-2');

    expect(calls()).toBe(2);
  });

  it('never uses the raw token as a key', async () => {
    const { repo: r } = repo(async () => session());
    const cache = new SessionCacheService(r, now);

    await cache.resolve('super-secret-token');

    const key = SessionCacheService.sessionKey('super-secret-token');
    expect(key).not.toContain('super-secret-token');
    expect(key).toHaveLength(64);
  });

  it('invalidate() forces the next resolve back to the database', async () => {
    const { repo: r, calls } = repo(async () => session());
    const cache = new SessionCacheService(r, now);

    await cache.resolve('token-1');
    cache.invalidate('token-1');
    await cache.resolve('token-1');

    // Logout must not leave the operator working off a cached entry.
    expect(calls()).toBe(2);
  });

  it('returns null and does NOT cache an unresolvable session', async () => {
    const { repo: r, calls } = repo(async () => null);
    const cache = new SessionCacheService(r, now);

    expect(await cache.resolve('bad-token')).toBeNull();
    expect(cache.size).toBe(0);
    await cache.resolve('bad-token');
    // Caching the rejection would keep refusing a token that was just
    // re-issued for the same value.
    expect(calls()).toBe(2);
  });

  it('returns null and does NOT cache a database outage', async () => {
    const { repo: r } = repo(async () => {
      throw new Error('ECONNREFUSED');
    });
    const cache = new SessionCacheService(r, now);

    // An outage must never be cached — it would lock every operator out
    // for the whole TTL even after Postgres recovers.
    expect(await cache.resolve('token-1')).toBeNull();
    expect(cache.size).toBe(0);
  });

  it('returns null for an empty token without querying', async () => {
    const { repo: r, calls } = repo(async () => session());
    const cache = new SessionCacheService(r, now);

    expect(await cache.resolve('')).toBeNull();
    expect(calls()).toBe(0);
  });

  it('evicts the least recently used entry past the cap', async () => {
    const { repo: r, calls } = repo(async () => session());
    const cache = new SessionCacheService(r, now);

    await cache.resolve('t1');
    await cache.resolve('t2');
    await cache.resolve('t3');
    await cache.resolve('t1'); // touch t1 so t2 becomes the oldest
    await cache.resolve('t4'); // cap is 3 → evicts t2

    expect(cache.size).toBe(3);
    const before = calls();
    await cache.resolve('t1');
    expect(calls()).toBe(before); // t1 survived
    await cache.resolve('t2');
    expect(calls()).toBe(before + 1); // t2 was evicted
  });

  it('invalidateAll() drops every entry', async () => {
    const { repo: r } = repo(async () => session());
    const cache = new SessionCacheService(r, now);

    await cache.resolve('t1');
    await cache.resolve('t2');
    cache.invalidateAll();

    expect(cache.size).toBe(0);
  });
});
