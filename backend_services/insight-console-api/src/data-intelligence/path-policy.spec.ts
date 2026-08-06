import { classify } from './path-policy';

/**
 * The Control Plane forwards commands; it is not an open proxy. This
 * classification is what makes that true, so a path it wrongly allows
 * is a path the browser chose.
 */
describe('classify', () => {
  describe('Explorer', () => {
    it.each([
      'pipelines',
      'pipelines/abc-123/execute',
      'executions/xyz/jobs',
      'review',
      'tickets',
      'runtime',
      'sources/enable',
      'data-intelligence/dashboard',
    ])('allows %s', (path) => {
      const decision = classify(path, 'GET');
      expect(decision).toEqual({ kind: 'allow', upstream: 'explorer', path });
    });

    it('matches on the first segment, so id-bearing paths need no listing', () => {
      const decision = classify('pipelines/9f3c/duplicate', 'POST');
      expect(decision.kind).toBe('allow');
    });
  });

  describe('Atlas routing', () => {
    it.each(['conflicts', 'ingestion', 'intelligence-graph', 'reasoning'])(
      'sends %s to the /atlas runtime router',
      (root) => {
        const decision = classify(`atlas/${root}`, 'GET');
        expect(decision).toEqual({
          kind: 'allow',
          upstream: 'atlas',
          path: `atlas/${root}`,
        });
      },
    );

    it('sends everything else to the historical intelligence router', () => {
      // These nine were once wrongly listed as runtime paths. They exist
      // ONLY under /v1/internal/intelligence, so routing them to /atlas
      // 404s — a latent trap for the next screen that uses them.
      for (const root of [
        'behaviors',
        'patterns',
        'signals',
        'trends',
        'market',
        'uncertainty',
        'memory',
        'head-to-head',
        'team-memory',
      ]) {
        expect(classify(`atlas/${root}`, 'GET')).toEqual({
          kind: 'allow',
          upstream: 'atlas',
          path: `v1/internal/intelligence/${root}`,
        });
      }
    });

    it('disambiguates `intelligence` by METHOD, not by path', () => {
      // POST /atlas/intelligence is runtime execution;
      // GET /v1/internal/intelligence/intelligence is a historical read.
      // The path is identical, so only the method separates them.
      expect(classify('atlas/intelligence', 'POST')).toMatchObject({
        path: 'atlas/intelligence',
      });
      expect(classify('atlas/intelligence', 'GET')).toMatchObject({
        path: 'v1/internal/intelligence/intelligence',
      });
    });

    it('routes datasets to the runtime router regardless of depth', () => {
      expect(classify('atlas/datasets/register', 'POST')).toMatchObject({
        path: 'atlas/datasets/register',
      });
    });
  });

  describe('default deny', () => {
    it.each([
      ['', 'empty'],
      ['atlas/', 'empty atlas path'],
      ['unknown-service', 'not an Explorer root'],
      ['admin/users', 'not an Explorer root'],
      ['../etc/passwd', 'traversal'],
      ['pipelines/../../secret', 'traversal inside an allowed root'],
    ])('refuses %s (%s)', (path) => {
      expect(classify(path, 'GET').kind).toBe('refuse');
    });

    it('refuses a path that merely starts with an allowed root name', () => {
      // `pipelinesX` is not `pipelines`; matching on a prefix STRING
      // rather than the first segment would let it through.
      expect(classify('pipelinesX/secret', 'GET').kind).toBe('refuse');
    });
  });

  describe('normalisation', () => {
    it('tolerates surrounding slashes', () => {
      expect(classify('/pipelines/', 'GET')).toMatchObject({
        upstream: 'explorer',
        path: 'pipelines',
      });
    });

    it('classifies on the path only, ignoring the query', () => {
      // The query is re-attached by the caller; letting it participate
      // here would make `?x=../` look like traversal and vice versa.
      expect(classify('review?status=pending', 'GET')).toMatchObject({
        upstream: 'explorer',
        path: 'review',
      });
    });
  });
});
