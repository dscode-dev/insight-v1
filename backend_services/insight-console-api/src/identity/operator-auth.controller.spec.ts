import { UnauthorizedException } from '@nestjs/common';
import type { FastifyRequest } from 'fastify';

import { SessionCacheService } from '../auth/session-cache.service';
import { IDENTITY_REQUEST_KEY, RequestWithIdentity } from './identity.guard';
import { OperatorAuthController } from './operator-auth.controller';
import type { OperatorRecord, OperatorRepository } from './operator.repository';

const OPERATOR: OperatorRecord = {
  id: 'op-1',
  username: 'ana',
  email: 'ana@konoha.lab',
  displayName: 'Ana',
  role: 'SuperAdmin',
  permissions: ['console.access', 'config.write'],
  isActive: true,
};

function request(overrides: Partial<FastifyRequest> = {}): FastifyRequest {
  return {
    headers: { 'user-agent': 'jest' },
    ip: '10.0.0.1',
    ...overrides,
  } as unknown as FastifyRequest;
}

describe('OperatorAuthController', () => {
  let revoked: string[];
  let invalidated: string[];
  let controller: OperatorAuthController;

  beforeEach(() => {
    revoked = [];
    invalidated = [];

    const operators = {
      authenticate: async (identifier: string, password: string) =>
        identifier === 'ana' && password === 'correct-password'
          ? OPERATOR
          : null,
      issueSession: async () => ({
        token: 'issued-token',
        sessionId: 'hash',
        expiresAt: new Date(Date.now() + 3_600_000),
        operator: OPERATOR,
      }),
      revokeSession: async (token: string) => {
        revoked.push(token);
      },
    } as unknown as OperatorRepository;

    const sessions = {
      invalidate: (token: string) => {
        invalidated.push(token);
      },
    } as unknown as SessionCacheService;

    controller = new OperatorAuthController(operators, sessions);
  });

  describe('login', () => {
    it('returns a session token and the operator', async () => {
      const result = await controller.login(request(), {
        identifier: 'ana',
        password: 'correct-password',
      });

      expect(result.session_token).toBe('issued-token');
      const operator = result.operator as Record<string, unknown>;
      // snake_case: the key the console's DTO already parses.
      expect(operator.display_name).toBe('Ana');
      expect(operator.permissions).toContain('config.write');
    });

    it('rejects a wrong password', async () => {
      await expect(
        controller.login(request(), { identifier: 'ana', password: 'wrong' }),
      ).rejects.toBeInstanceOf(UnauthorizedException);
    });

    it('answers an unknown identifier exactly like a wrong password', async () => {
      // Distinguishable answers would turn the login form into an
      // account-enumeration oracle.
      const wrongPassword = await controller
        .login(request(), { identifier: 'ana', password: 'wrong' })
        .catch((e: UnauthorizedException) => e.getResponse());
      const unknownUser = await controller
        .login(request(), { identifier: 'nobody', password: 'correct-password' })
        .catch((e: UnauthorizedException) => e.getResponse());

      expect(unknownUser).toEqual(wrongPassword);
    });

    it('never echoes the password back', async () => {
      const result = await controller.login(request(), {
        identifier: 'ana',
        password: 'correct-password',
      });
      expect(JSON.stringify(result)).not.toContain('correct-password');
    });
  });

  describe('logout', () => {
    function authenticated(token: string): RequestWithIdentity {
      const req = request({
        headers: { authorization: `Bearer ${token}` },
      } as Partial<FastifyRequest>) as RequestWithIdentity;
      req[IDENTITY_REQUEST_KEY] = {
        operator: OPERATOR,
        sessionId: 'hash',
        expiresAt: new Date(),
        token,
      };
      return req;
    }

    it('revokes the session AND drops it from the cache', async () => {
      await controller.logout(authenticated('live-token'));

      expect(revoked).toEqual(['live-token']);
      // Revoking in the database alone is not enough: the resolution
      // cache would keep answering for the whole TTL, so a logged-out
      // operator stayed authenticated for another 30 seconds. Found by
      // an end-to-end logout test — revocation and caching are each
      // correct in isolation.
      expect(invalidated).toEqual(['live-token']);
    });

    it('is a no-op without a bearer token', async () => {
      await controller.logout(request() as RequestWithIdentity);

      expect(revoked).toEqual([]);
      expect(invalidated).toEqual([]);
    });
  });

  describe('me', () => {
    it('refuses when the guard parked no identity', async () => {
      await expect(
        controller.me(request() as RequestWithIdentity),
      ).rejects.toBeInstanceOf(UnauthorizedException);
    });
  });
});
