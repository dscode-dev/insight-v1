/**
 * Rejects any request that does not carry a live operator session.
 *
 * WHAT CHANGED AND WHY. This guard used to verify an HMAC envelope the
 * Next.js console signed, because the console resolved identity itself
 * (against the Gateway) and told this service who the operator was.
 * insight-context.md v2.0 puts "Autenticação administrativa, Sessões de
 * operadores, RBAC" on the Control Plane and states the Gateway is not
 * responsible for operators — so the direction is now inverted: this
 * service IS the authority, and the console presents the session token
 * it holds in its cookie.
 *
 * That also removes a round-trip. Under the envelope scheme the console
 * had to resolve identity somewhere before it could sign anything, so
 * every request cost a resolution call plus the call it actually wanted.
 *
 * Applied globally: @Public marks the few surfaces that cannot require
 * a session (health, and login itself).
 */
import {
  CanActivate,
  ExecutionContext,
  Injectable,
  Logger,
  UnauthorizedException,
} from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import type { FastifyRequest } from 'fastify';

import { SessionCacheService } from '../auth/session-cache.service';
import type { OperatorRecord } from './operator.repository';
import { IS_PUBLIC_KEY } from './public.decorator';

/** Where the resolved operator is parked for controllers to read. */
export const IDENTITY_REQUEST_KEY = 'consoleIdentity';

export interface RequestIdentity {
  readonly operator: OperatorRecord;
  readonly sessionId: string;
  readonly expiresAt: Date;
  /** The raw bearer token, so logout can revoke the exact session. */
  readonly token: string;
}

export interface RequestWithIdentity extends FastifyRequest {
  [IDENTITY_REQUEST_KEY]?: RequestIdentity;
}

@Injectable()
export class IdentityGuard implements CanActivate {
  private readonly logger = new Logger(IdentityGuard.name);

  constructor(
    private readonly reflector: Reflector,
    private readonly sessions: SessionCacheService,
  ) {}

  async canActivate(context: ExecutionContext): Promise<boolean> {
    const isPublic = this.reflector.getAllAndOverride<boolean>(IS_PUBLIC_KEY, [
      context.getHandler(),
      context.getClass(),
    ]);
    if (isPublic) {
      return true;
    }

    const request = context.switchToHttp().getRequest<RequestWithIdentity>();
    const token = bearerToken(request);
    if (!token) {
      throw new UnauthorizedException('operator_session_required');
    }

    const resolved = await this.sessions.resolve(token);
    if (resolved === null) {
      // Never log the token, and never say WHY: expired, revoked,
      // unknown and belonging-to-a-deactivated-operator all look the
      // same from outside on purpose.
      this.logger.warn('rejected a request with no live operator session');
      throw new UnauthorizedException('operator_session_required');
    }

    request[IDENTITY_REQUEST_KEY] = { ...resolved, token };
    return true;
  }
}

export function bearerToken(request: FastifyRequest): string {
  const raw = request.headers.authorization;
  if (typeof raw !== 'string') {
    return '';
  }
  const [scheme, ...rest] = raw.split(' ');
  if (!scheme || scheme.toLowerCase() !== 'bearer') {
    return '';
  }
  return rest.join(' ').trim();
}
