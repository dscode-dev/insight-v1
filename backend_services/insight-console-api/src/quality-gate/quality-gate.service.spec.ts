import { loadConfig, resetConfigForTests } from '../config/config';
import { UpstreamError, UpstreamService } from '../upstream/upstream.service';
import { QualityEvaluation, summarizeGate } from './quality-gate.contracts';
import { QualityGateService } from './quality-gate.service';

const BASE_ENV = {
  CONSOLE_API_SIGNING_SECRET: 'a'.repeat(48),
  ROBOZAO_GATEWAY_URL: 'http://gateway:8095',
  ATLAS_API_BASE_URL: 'http://atlas:8085',
  ATLAS_INTERNAL_TOKEN: 'internal-token',
};

/**
 * Fetcher driven by a path→response map, matched on the URL SUFFIX.
 *
 * Not `includes`: `/backtests/exec-1/quality` contains
 * `/backtests/exec-1`, so a substring matcher silently answers the
 * sub-resource calls with the execution's own payload and the test
 * passes for the wrong reason.
 */
function router(routes: Record<string, () => Response>): jest.Mock {
  return jest.fn().mockImplementation(async (url: string) => {
    for (const [suffix, make] of Object.entries(routes)) {
      if (url.endsWith(suffix)) {
        return make();
      }
    }
    return new Response('', { status: 404 });
  });
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function evaluation(overrides: Partial<QualityEvaluation> = {}): QualityEvaluation {
  return {
    replay_hash: 'hash-candidate',
    promotions: [
      { agent: 'trend_engine', trend_type: 'momentum', verdict: 'Approved', reasons: [] },
    ],
    regression: {
      quality_regression: false,
      confidence_regression: false,
      detector_regression: false,
      trend_regression: false,
      similarity_regression: false,
      reasoning_regression: false,
      diff: {
        identical: true,
        baseline_hash: 'hash-baseline',
        candidate_hash: 'hash-candidate',
        new_detections: [],
        lost_detections: [],
        confidence_changes: [],
        strength_changes: [],
        trend_changes: [],
      },
    },
    ...overrides,
  };
}

describe('summarizeGate', () => {
  it('reports nothing required for a clean evaluation with a baseline', () => {
    const gate = summarizeGate(evaluation());
    expect(gate.evaluated).toBe(true);
    expect(gate.hasBaseline).toBe(true);
    expect(gate.requiresOverride).toBe(false);
    expect(gate.requiresBaselineAck).toBe(false);
  });

  it('requires an override when any detector verdict is Rejected', () => {
    const gate = summarizeGate(
      evaluation({
        promotions: [
          { agent: 'a', trend_type: 'x', verdict: 'Approved', reasons: [] },
          { agent: 'a', trend_type: 'y', verdict: 'Rejected', reasons: ['lost'] },
        ],
      }),
    );
    expect(gate.requiresOverride).toBe(true);
    expect(gate.blocking).toHaveLength(1);
    expect(gate.verdictCounts).toEqual({ Approved: 1, Rejected: 1 });
  });

  it('requires an override on quality_regression even with no Rejected verdict', () => {
    // A candidate can keep every detection and still weaken all of them
    // — quality.py calls that Warning. It must not read as "clean".
    const base = evaluation();
    const gate = summarizeGate({
      ...base,
      promotions: [
        { agent: 'a', trend_type: 'x', verdict: 'Warning', reasons: [] },
      ],
      regression: { ...base.regression!, quality_regression: true },
    });
    expect(gate.requiresOverride).toBe(true);
  });

  it('requires a baseline acknowledgement when nothing was diffed', () => {
    const gate = summarizeGate(evaluation({ regression: null }));
    expect(gate.hasBaseline).toBe(false);
    expect(gate.requiresBaselineAck).toBe(true);
  });

  it('reports not-evaluated for a replay with no quality yet', () => {
    const gate = summarizeGate(null);
    expect(gate.evaluated).toBe(false);
    // Must NOT ask for an override/ack on a replay that hasn't been
    // evaluated — there is nothing to override yet.
    expect(gate.requiresOverride).toBe(false);
    expect(gate.requiresBaselineAck).toBe(false);
  });
});

describe('QualityGateService', () => {
  beforeEach(() => {
    resetConfigForTests();
    process.env = { ...process.env, ...BASE_ENV } as NodeJS.ProcessEnv;
    loadConfig(process.env);
  });

  afterEach(() => resetConfigForTests());

  function service(fetcher: jest.Mock): QualityGateService {
    return new QualityGateService(
      new UpstreamService(fetcher as unknown as typeof fetch),
    );
  }

  describe('review', () => {
    it('composes execution, quality, manifest and decision in one answer', async () => {
      const fetcher = router({
        '/quality': () => json(evaluation()),
        '/manifest': () => json({ replay_engine_version: '1' }),
        '/decision': () => json({ id: 'd1', verdict: 'approved' }),
        '/backtests/exec-1': () => json({ execution_id: 'exec-1', status: 'completed' }),
      });

      const review = await service(fetcher).review('exec-1');

      expect(review.execution.status).toBe('completed');
      expect(review.quality?.replay_hash).toBe('hash-candidate');
      expect(review.manifest).not.toBeNull();
      expect(review.decision?.verdict).toBe('approved');
      expect(review.gate.evaluated).toBe(true);
    });

    it('maps a 404 sub-resource to null instead of failing the screen', async () => {
      // While a replay is still running, quality/manifest/decision all
      // 404 legitimately.
      const fetcher = router({
        '/backtests/exec-1': () => json({ execution_id: 'exec-1', status: 'running' }),
      });

      const review = await service(fetcher).review('exec-1');

      expect(review.execution.status).toBe('running');
      expect(review.quality).toBeNull();
      expect(review.manifest).toBeNull();
      expect(review.decision).toBeNull();
      expect(review.gate.evaluated).toBe(false);
    });

    it('does NOT swallow a non-404 upstream failure', async () => {
      // Degrading a 500 to null would render an "in progress" screen
      // for a broken Atlas.
      const fetcher = jest.fn().mockImplementation(async (url: string) =>
        url.endsWith('/backtests/exec-1')
          ? json({ execution_id: 'exec-1' })
          : new Response('', { status: 500 }),
      );

      await expect(service(fetcher).review('exec-1')).rejects.toThrow(UpstreamError);
    });

    it('propagates a failure to fetch the execution itself', async () => {
      const fetcher = router({});
      await expect(service(fetcher).review('nope')).rejects.toThrow(UpstreamError);
    });
  });

  describe('decide', () => {
    it('sends the operator as X-Operator, not in the body', async () => {
      const fetcher = router({ '/decision': () => json({ id: 'd1' }) });

      await service(fetcher).decide('ana', 'exec-1', {
        verdict: 'approved',
        reason: 'looks right',
      });

      const [, init] = fetcher.mock.calls[0] as [string, RequestInit];
      expect((init.headers as Record<string, string>)['X-Operator']).toBe('ana');
      // Atlas derives decided_by from the header; a body field would be
      // a second, spoofable source of attribution.
      expect(JSON.parse(init.body as string)).not.toHaveProperty('decided_by');
    });

    it('surfaces the gate refusal code so the screen can act on it', async () => {
      const fetcher = router({
        '/decision': () =>
          json(
            {
              detail: {
                code: 'override_required',
                message: 'the Quality Gate did not clear this replay',
              },
            },
            409,
          ),
      });

      // The code is the ONLY thing telling the operator that an
      // explicit override is what's missing.
      await expect(
        service(fetcher).decide('ana', 'exec-1', {
          verdict: 'approved',
          reason: 'ship it',
        }),
      ).rejects.toMatchObject({
        status: 409,
        refusal: { code: 'override_required' },
      });
    });

    it('does not leak an unrecognised error body', async () => {
      // Whitelist, not passthrough: a body that doesn't match the
      // {detail:{code,message}} contract must produce no refusal at all.
      const fetcher = router({
        '/decision': () => json({ internal_token: 'super-secret' }, 500),
      });

      const error = await service(fetcher)
        .decide('ana', 'exec-1', { verdict: 'approved', reason: 'x' })
        .catch((e: unknown) => e);

      expect(error).toBeInstanceOf(UpstreamError);
      expect((error as UpstreamError).refusal).toBeUndefined();
      expect(JSON.stringify(error)).not.toContain('super-secret');
    });
  });

  describe('submitReplay', () => {
    it('overrides any client-supplied requester with the verified actor', async () => {
      const fetcher = router({ backtests: () => json({ execution_id: 'e1' }) });

      await service(fetcher).submitReplay('ana', {
        source: 'season',
        competition: 'brasileirao',
        season: '2025',
        // A caller trying to attribute the run to someone else.
        ...({ requester: 'someone-else' } as object),
      });

      const [, init] = fetcher.mock.calls[0] as [string, RequestInit];
      expect(JSON.parse(init.body as string).requester).toBe('ana');
    });
  });
});
