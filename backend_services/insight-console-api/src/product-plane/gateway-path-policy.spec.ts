import { classifyGatewayPath } from './gateway-path-policy';

describe('gateway path policy', () => {
  it('allows the administrative surfaces the console screens use', () => {
    for (const path of [
      '/v1/console/admin/operators',
      '/v1/console/admin/sessions',
      '/v1/console/admin/users',
      '/v1/console/social/enforcement/post/abc',
      '/v1/console/identity/delegations',
      '/v1/console/platform/health',
      '/v1/admin/moderation/actions',
    ]) {
      expect(classifyGatewayPath(path)).toEqual({ kind: 'allow', path });
    }
  });

  it('refuses anything not on the list', () => {
    for (const path of [
      '/v1/auth/phone/request',
      '/v1/feed',
      '/v1/users/me/preferences',
      '/healthz',
      '/',
    ]) {
      expect(classifyGatewayPath(path).kind).toBe('refuse');
    }
  });

  it('refuses traversal and ambiguous slashes', () => {
    expect(classifyGatewayPath('/v1/console/admin/../../etc').kind).toBe('refuse');
    expect(classifyGatewayPath('/v1/console//admin/users').kind).toBe('refuse');
  });

  // An exact-match prefix must not also match a longer sibling name.
  it('does not let a prefix match a different resource', () => {
    expect(classifyGatewayPath('/v1/console/admin/operatorsX').kind).toBe('refuse');
    expect(classifyGatewayPath('/v1/console/admin/operators/1').kind).toBe('allow');
  });

  it('normalises a path without a leading slash', () => {
    expect(classifyGatewayPath('v1/console/admin/users')).toEqual({
      kind: 'allow',
      path: '/v1/console/admin/users',
    });
  });

  it('ignores the query string when matching', () => {
    expect(classifyGatewayPath('/v1/console/admin/users?limit=10')).toEqual({
      kind: 'allow',
      path: '/v1/console/admin/users',
    });
  });

  // Fase C: these arrived from the Node Agent's deleted HTTPExecutor. The
  // capability has to have a home, or removing the proxy would just lose it.
  describe('internal operations (moved off the Node Agent)', () => {
    it('allows the four surfaces the proxy used to reach', () => {
      for (const path of [
        '/v1/internal/operations/dlq/failure-1/replay',
        '/v1/internal/operations/users/user-1/sessions/revoke',
        '/v1/internal/operations/social/agents/agent-1/deactivate',
        '/v1/internal/operations/social/content/post/post-1/hide',
      ]) {
        expect(classifyGatewayPath(path)).toEqual({ kind: 'allow', path });
      }
    });

    // The allow-list is prefix-matched, so it is worth pinning that the
    // prefix is `/v1/internal/operations/` and not `/v1/internal/`.
    it('does not open the rest of /v1/internal', () => {
      expect(classifyGatewayPath('/v1/internal/secrets').kind).toBe('refuse');
      expect(classifyGatewayPath('/v1/internal/').kind).toBe('refuse');
    });

    it('still refuses traversal out of the operations prefix', () => {
      expect(
        classifyGatewayPath('/v1/internal/operations/../../admin').kind,
      ).toBe('refuse');
    });
  });
});
