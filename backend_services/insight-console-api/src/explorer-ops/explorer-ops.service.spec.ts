import { loadConfig, resetConfigForTests } from '../config/config';
import { UpstreamService } from '../upstream/upstream.service';
import { ExplorerOpsService } from './explorer-ops.service';

const BASE_ENV = {
  CONTROL_PLANE_DATABASE_URL: 'postgres://u:p@postgres:5432/insight_db',
  ROBOZAO_GATEWAY_URL: 'http://robozao-gateway:8095',
  EXPLORER_API_BASE_URL: 'http://insight-explorer:8090',
  EXPLORER_OPS_TOKEN: 'ops-token',
};

function okFetcher(body: unknown = {}): jest.Mock {
  return jest.fn().mockImplementation(async () =>
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }),
  );
}

function callOf(fetcher: jest.Mock, index = 0): { url: string; init: RequestInit } {
  const [url, init] = fetcher.mock.calls[index] as [string, RequestInit];
  return { url, init };
}

describe('ExplorerOpsService', () => {
  beforeEach(() => {
    resetConfigForTests();
    process.env = { ...process.env, ...BASE_ENV } as NodeJS.ProcessEnv;
    loadConfig(process.env);
  });

  afterEach(() => resetConfigForTests());

  function service(fetcher: jest.Mock): ExplorerOpsService {
    return new ExplorerOpsService(
      new UpstreamService(fetcher as unknown as typeof fetch),
    );
  }

  describe('review', () => {
    it('defaults the queue to pending', async () => {
      const fetcher = okFetcher({ items: [], stats: {} });
      await service(fetcher).reviewQueue();
      expect(callOf(fetcher).url).toContain('review?status=pending');
    });

    it('scopes the queue by competition when given one', async () => {
      const fetcher = okFetcher();
      await service(fetcher).reviewQueue('pending', 'brasileirao');
      expect(callOf(fetcher).url).toContain('competition=brasileirao');
    });

    it.each([
      ['reviewPromote', 'review/promote'],
      ['reviewReject', 'review/reject'],
    ] as const)('%s sends the operator as X-Operator', async (method, path) => {
      const fetcher = okFetcher();
      await service(fetcher)[method]('ana', 'ext-1');

      const { url, init } = callOf(fetcher);
      expect(url).toContain(path);
      // Explorer records this actor in its own audit log; the browser
      // must never be able to name it.
      expect((init.headers as Record<string, string>)['X-Operator']).toBe('ana');
      expect(JSON.parse(init.body as string)).toEqual({ external_id: 'ext-1' });
    });

    it('sends the ops token — Explorer 401s on every call without it', async () => {
      const fetcher = okFetcher();
      await service(fetcher).reviewQueue();
      expect((callOf(fetcher).init.headers as Record<string, string>)['X-Ops-Token']).toBe(
        'ops-token',
      );
    });

    it('refuses to call at all when the ops token is unset', async () => {
      resetConfigForTests();
      process.env = {
        ...process.env,
        ...BASE_ENV,
        EXPLORER_OPS_TOKEN: '',
      } as NodeJS.ProcessEnv;
      loadConfig(process.env);

      const fetcher = okFetcher();
      // Failing loudly beats sending an unauthenticated request and
      // surfacing Explorer's 401 as if the operator lacked permission.
      await expect(service(fetcher).reviewQueue()).rejects.toThrow(
        'explorer_ops_token_missing',
      );
      expect(fetcher).not.toHaveBeenCalled();
    });
  });

  describe('jobs', () => {
    it('resolves active and history together', async () => {
      const fetcher = okFetcher([]);
      const overview = await service(fetcher).jobsOverview(25);

      expect(overview).toHaveProperty('active');
      expect(overview).toHaveProperty('history');
      const urls = fetcher.mock.calls.map((c) => String(c[0]));
      expect(urls.some((u) => u.includes('jobs/active'))).toBe(true);
      expect(urls.some((u) => u.includes('jobs/history?limit=25'))).toBe(true);
    });

    it('sends competition and season for a task-scoped action', async () => {
      const fetcher = okFetcher();
      await service(fetcher).taskAction('ana', 'restart', 'brasileirao', '2025');

      const { url, init } = callOf(fetcher);
      expect(url).toContain('jobs/restart');
      expect(JSON.parse(init.body as string)).toEqual({
        competition: 'brasileirao',
        season: '2025',
      });
    });

    it('sends no task scope for a scheduler-wide action', async () => {
      const fetcher = okFetcher();
      await service(fetcher).schedulerAction('ana', 'cancel');

      const { url, init } = callOf(fetcher);
      expect(url).toContain('jobs/cancel');
      // pause/resume/cancel act on the WHOLE scheduler and take no body.
      // Sending a competition/season here would suggest a per-task
      // scope that does not exist.
      expect(JSON.parse(init.body as string)).toEqual({});
    });
  });

  describe('quality', () => {
    it('composes the four quality surfaces in one answer', async () => {
      const fetcher = okFetcher({});
      const overview = await service(fetcher).qualityOverview();

      expect(Object.keys(overview).sort()).toEqual([
        'datasets',
        'duplicates',
        'entityResolution',
        'summary',
      ]);
      expect(fetcher).toHaveBeenCalledTimes(4);
    });
  });

  describe('runtime', () => {
    it('passes /runtime through rather than recomposing it', async () => {
      const fetcher = okFetcher({ status: {}, scheduler: {} });
      await service(fetcher).runtime();
      // Explorer already aggregates status+scheduler+sources+qwen+
      // storage+config there; recomposing would be four extra hops.
      expect(fetcher).toHaveBeenCalledTimes(1);
      expect(callOf(fetcher).url).toContain('/explorer/runtime');
    });

    it('attributes a config reload to the operator', async () => {
      const fetcher = okFetcher();
      await service(fetcher).reloadRuntime('ana');
      expect((callOf(fetcher).init.headers as Record<string, string>)['X-Operator']).toBe(
        'ana',
      );
    });
  });
});
