import { classifySocialPath } from './social-path-policy';

describe('social path policy', () => {
  it('allows the read surfaces the console screens use', () => {
    for (const path of [
      'overview',
      'activity',
      'users',
      'users/9c1f0f5e-1111-4444-8888-aaaaaaaaaaaa',
      'agents',
      'agents/abc',
      'posts',
      'posts/abc',
      'comments',
      'comments/abc',
      'communities',
      'communities/abc',
      'relationships',
      'boosts',
      'timeline',
    ]) {
      expect(classifySocialPath(path, 'GET')).toEqual({
        kind: 'allow',
        path: `/${path}`,
      });
    }
  });

  it('refuses an unknown root', () => {
    expect(classifySocialPath('feed', 'GET').kind).toBe('refuse');
    expect(classifySocialPath('auth/login', 'POST').kind).toBe('refuse');
  });

  // Prefix matching would let this through; first-segment matching does not.
  it('refuses a root that merely starts with an allowed one', () => {
    expect(classifySocialPath('usersX', 'GET').kind).toBe('refuse');
    expect(classifySocialPath('posts-internal', 'GET').kind).toBe('refuse');
  });

  it('refuses traversal', () => {
    expect(classifySocialPath('users/../../healthz', 'GET').kind).toBe('refuse');
  });

  it('refuses an empty path', () => {
    expect(classifySocialPath('', 'GET').kind).toBe('refuse');
    expect(classifySocialPath('   ', 'GET').kind).toBe('refuse');
  });

  describe('writes', () => {
    it('allows the two enumerated agent-state commands', () => {
      for (const [method, path] of [
        ['POST', 'agents/9c1f0f5e-1111-4444-8888-aaaaaaaaaaaa/deactivate'],
        ['POST', 'agents/9c1f0f5e-1111-4444-8888-aaaaaaaaaaaa/reactivate'],
      ] as ReadonlyArray<readonly [string, string]>) {
        expect(classifySocialPath(path, method)).toEqual({
          kind: 'allow',
          path: `/${path}`,
        });
      }
    });

    // The point of enumerating rather than allowing by root: `users` is
    // readable, and a root-level write allow would make a destructive route
    // reachable the day someone adds it upstream.
    it('refuses any write that is not on the list', () => {
      expect(classifySocialPath('users/abc/ban', 'POST').kind).toBe('refuse');
      expect(classifySocialPath('users/abc', 'DELETE').kind).toBe('refuse');
      expect(classifySocialPath('posts/abc/hide', 'POST').kind).toBe('refuse');
      expect(classifySocialPath('overview', 'POST').kind).toBe('refuse');
    });

    // A data segment must never be read as a literal that unlocks a route.
    it('refuses a write whose id position holds a literal', () => {
      expect(classifySocialPath('agents/deactivate', 'POST').kind).toBe('refuse');
    });

    it('names the refused write so the reason is actionable', () => {
      const decision = classifySocialPath('users/abc/ban', 'POST');
      expect(decision.kind).toBe('refuse');
      if (decision.kind === 'refuse') {
        expect(decision.reason).toContain('POST');
        expect(decision.reason).toContain('/users/abc/ban');
      }
    });
  });
  describe('competition registry', () => {
    it('allows reading the registry', () => {
      expect(classifySocialPath('competitions', 'GET')).toEqual({
        kind: 'allow',
        path: '/competitions',
      });
    });

    it('allows the four registry operations', () => {
      expect(classifySocialPath('competitions', 'POST').kind).toBe('allow');
      expect(
        classifySocialPath('competitions/ef8a4e4b-b986-4e2a-b9b9-467b8135ad33', 'PATCH').kind,
      ).toBe('allow');
      expect(
        classifySocialPath('competitions/ef8a4e4b-b986-4e2a-b9b9-467b8135ad33', 'DELETE').kind,
      ).toBe('allow');
    });

    // DELETE without an id would be "delete the collection". Social has no
    // such route, so this would 404 — but the allow-list is the layer that
    // should say no, not the far side's routing table.
    it('refuses a collection-level delete', () => {
      expect(classifySocialPath('competitions', 'DELETE').kind).toBe('refuse');
    });

    it('refuses methods nobody implemented', () => {
      expect(classifySocialPath('competitions/abc', 'PUT').kind).toBe('refuse');
      expect(classifySocialPath('competitions/abc/publish', 'POST').kind).toBe('refuse');
    });

    it('refuses traversal out of the registry', () => {
      expect(classifySocialPath('competitions/../users/abc/ban', 'POST').kind).toBe('refuse');
    });
  });
});
