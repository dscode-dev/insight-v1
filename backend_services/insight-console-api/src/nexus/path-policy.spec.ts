import { classify } from './path-policy';

describe('nexus path policy', () => {
  it('allows reads under known roots', () => {
    for (const path of [
      'v1/agents',
      'v1/publications/candidates',
      'v1/publications/tickets',
      'v1/publication-decisions',
      'v1/trend-clusters',
      'v1/narrative-health',
      'v1/drafts/evolution',
      'v1/personas',
      'v1/llm/health',
      'v1/audit/events',
      'v1/dlq/trends',
    ]) {
      expect(classify(path, 'GET')).toEqual({ kind: 'allow', path: `/${path}` });
    }
  });

  it('refuses an unknown root', () => {
    expect(classify('v1/secrets', 'GET').kind).toBe('refuse');
  });

  // Prefix matching would let this through; first-segment matching does not.
  it('refuses a root that merely starts with an allowed one', () => {
    expect(classify('v1/agentsX/leak', 'GET').kind).toBe('refuse');
    expect(classify('v1/agents-internal', 'GET').kind).toBe('refuse');
  });

  it('refuses traversal', () => {
    expect(classify('v1/agents/../../etc', 'GET').kind).toBe('refuse');
  });

  it('refuses an empty path', () => {
    expect(classify('', 'GET').kind).toBe('refuse');
    expect(classify('   ', 'GET').kind).toBe('refuse');
  });

  // /live and /metrics are platform probes, not operator surfaces.
  it('refuses anything outside /v1', () => {
    expect(classify('live', 'GET').kind).toBe('refuse');
    expect(classify('metrics', 'GET').kind).toBe('refuse');
    expect(classify('healthz', 'GET').kind).toBe('refuse');
  });

  describe('writes', () => {
    it('allows the enumerated ones', () => {
      const cases: ReadonlyArray<readonly [string, string]> = [
        ['POST', 'v1/agents'],
        ['PUT', 'v1/agents/9c1f0f5e-1111-4444-8888-aaaaaaaaaaaa'],
        ['POST', 'v1/agents/9c1f0f5e-1111-4444-8888-aaaaaaaaaaaa/enable'],
        ['POST', 'v1/agents/9c1f0f5e-1111-4444-8888-aaaaaaaaaaaa/disable'],
        ['PATCH', 'v1/publications/tickets/abc-123'],
        ['POST', 'v1/publications/tickets/abc-123/publish'],
        ['POST', 'v1/publications/manual'],
        ['PUT', 'v1/personas/oracle'],
        ['POST', 'v1/audit/events'],
        ['POST', 'v1/dlq/trends/entry-1/replay'],
      ];
      for (const [method, path] of cases) {
        expect(classify(path, method)).toEqual({
          kind: 'allow',
          path: `/${path}`,
        });
      }
    });

    // The point of enumerating: a write nobody approved is refused even
    // though its ROOT is readable.
    it('refuses an unlisted write under an allowed root', () => {
      expect(classify('v1/agents/abc', 'DELETE').kind).toBe('refuse');
      expect(classify('v1/personas/oracle', 'DELETE').kind).toBe('refuse');
      expect(classify('v1/publications/candidates', 'POST').kind).toBe('refuse');
      expect(classify('v1/trend-clusters', 'POST').kind).toBe('refuse');
    });

    // A persona slug shaped like a uuid must behave like any other slug.
    it('does not depend on the shape of the id', () => {
      expect(
        classify('v1/personas/9c1f0f5e-1111-4444-8888-aaaaaaaaaaaa', 'PUT').kind,
      ).toBe('allow');
      expect(classify('v1/publications/tickets/oracle', 'PATCH').kind).toBe(
        'allow',
      );
    });

    // A data segment must never be read as a literal that unlocks a
    // different route.
    it('refuses a write whose id position holds a literal', () => {
      expect(classify('v1/agents/enable', 'POST').kind).toBe('refuse');
    });

    it('names the refused write so the reason is actionable', () => {
      const decision = classify('v1/agents/abc', 'DELETE');
      expect(decision.kind).toBe('refuse');
      if (decision.kind === 'refuse') {
        expect(decision.reason).toContain('DELETE');
        expect(decision.reason).toContain('/v1/agents/abc');
      }
    });
  });
});
