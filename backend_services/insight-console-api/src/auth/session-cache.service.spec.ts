import { loadConfig, resetConfigForTests } from '../config/config';
import { SessionCacheService } from './session-cache.service';

const BASE_ENV = {
  CONSOLE_API_SIGNING_SECRET: 'a'.repeat(48),
  ROBOZAO_GATEWAY_URL: 'http://gateway:8095',
  SESSION_CACHE_TTL_SECONDS: '30',
  SESSION_CACHE_MAX_ENTRIES: '3',
};

/**
 * Returns a fetcher that yields a FRESH Response per call.
 *
 * `mockResolvedValue(new Response(...))` hands back the same instance
 * every time, and a Response body can only be consumed once — the
 * second resolve() then fails to parse and silently returns null,
 * which makes multi-call tests pass or fail for the wrong reason.
 */
function okFetcher(body: unknown): jest.Mock {
  return jest.fn().mockImplementation(async () =>
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }),
  );
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

  it('calls the gateway on a miss and returns the operator', async () => {
    const fetcher = okFetcher({
      id: 'op-1', username: 'ana', role: 'SuperAdmin', permissions: ['a'],
    });
    const cache = new SessionCacheService(fetcher as unknown as typeof fetch, now);

    const session = await cache.resolve('token-1');

    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(session?.operatorId).toBe('op-1');
    expect(session?.permissions).toEqual(['a']);
  });

  it('serves a second request from cache without hitting the gateway', async () => {
    const fetcher = okFetcher({ id: 'op-1' });
    const cache = new SessionCacheService(fetcher as unknown as typeof fetch, now);

    await cache.resolve('token-1');
    await cache.resolve('token-1');

    // This is the entire point of the service.
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('re-resolves once the TTL expires', async () => {
    const fetcher = okFetcher({ id: 'op-1' });
    const cache = new SessionCacheService(fetcher as unknown as typeof fetch, now);

    await cache.resolve('token-1');
    clock += 31_000; // TTL is 30s
    await cache.resolve('token-1');

    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('keys on the token, not the operator', async () => {
    const fetcher = okFetcher({ id: 'op-1' });
    const cache = new SessionCacheService(fetcher as unknown as typeof fetch, now);

    await cache.resolve('token-1');
    await cache.resolve('token-2');

    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('never stores the raw token as a key', async () => {
    const fetcher = okFetcher({ id: 'op-1' });
    const cache = new SessionCacheService(fetcher as unknown as typeof fetch, now);

    const session = await cache.resolve('super-secret-token');

    expect(session?.sessionId).toBe(
      SessionCacheService.sessionKey('super-secret-token'),
    );
    expect(session?.sessionId).not.toContain('super-secret-token');
  });

  it('invalidate() forces the next resolve back to the gateway', async () => {
    const fetcher = okFetcher({ id: 'op-1' });
    const cache = new SessionCacheService(fetcher as unknown as typeof fetch, now);

    await cache.resolve('token-1');
    cache.invalidate('token-1');
    await cache.resolve('token-1');

    // Logout must not leave the operator working off a cached entry.
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('returns null and does NOT cache when the gateway rejects the token', async () => {
    const fetcher = jest
      .fn()
      .mockImplementation(async () => new Response('', { status: 401 }));
    const cache = new SessionCacheService(fetcher as unknown as typeof fetch, now);

    expect(await cache.resolve('bad-token')).toBeNull();
    expect(cache.size).toBe(0);
    await cache.resolve('bad-token');
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('returns null and does NOT cache when the gateway is unreachable', async () => {
    const fetcher = jest.fn().mockRejectedValue(new Error('ECONNREFUSED'));
    const cache = new SessionCacheService(fetcher as unknown as typeof fetch, now);

    // An outage must never be cached — that would lock every operator
    // out for the whole TTL even after the gateway recovers.
    expect(await cache.resolve('token-1')).toBeNull();
    expect(cache.size).toBe(0);
  });

  it('rejects a gateway response with no operator id', async () => {
    const fetcher = okFetcher({ username: 'ana' });
    const cache = new SessionCacheService(fetcher as unknown as typeof fetch, now);

    expect(await cache.resolve('token-1')).toBeNull();
  });

  it('accepts operator_id as well as id', async () => {
    const fetcher = okFetcher({ operator_id: 'op-9' });
    const cache = new SessionCacheService(fetcher as unknown as typeof fetch, now);

    expect((await cache.resolve('token-1'))?.operatorId).toBe('op-9');
  });

  it('evicts the least recently used entry past the cap', async () => {
    const fetcher = okFetcher({ id: 'op-1' });
    const cache = new SessionCacheService(fetcher as unknown as typeof fetch, now);

    await cache.resolve('t1');
    await cache.resolve('t2');
    await cache.resolve('t3');
    await cache.resolve('t1'); // touch t1 so t2 becomes the oldest
    await cache.resolve('t4'); // cap is 3 → evicts t2

    expect(cache.size).toBe(3);
    fetcher.mockClear();
    await cache.resolve('t1');
    expect(fetcher).not.toHaveBeenCalled(); // t1 survived
    await cache.resolve('t2');
    expect(fetcher).toHaveBeenCalledTimes(1); // t2 was evicted
  });

  it('returns null for an empty token without calling the gateway', async () => {
    const fetcher = jest.fn();
    const cache = new SessionCacheService(fetcher as unknown as typeof fetch, now);

    expect(await cache.resolve('')).toBeNull();
    expect(fetcher).not.toHaveBeenCalled();
  });
});
