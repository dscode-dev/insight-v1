import {
  BadRequestException,
  Body,
  Controller,
  Get,
  HttpCode,
  Logger,
  Post,
  Req,
  UnauthorizedException,
} from '@nestjs/common';
import type { FastifyRequest } from 'fastify';

import { SessionCacheService } from '../auth/session-cache.service';
import { Public } from './public.decorator';
import { OperatorRepository } from './operator.repository';
import { IDENTITY_REQUEST_KEY, RequestWithIdentity } from './identity.guard';

interface LoginBody {
  readonly identifier?: string;
  readonly password?: string;
}

/**
 * Administrative authentication. THE Control Plane's core job.
 *
 * insight-context.md v2.0 assigns "Autenticação administrativa" and
 * "Sessões de operadores" to the Control Plane, and states that the
 * Insight Gateway is not responsible for operators or administration.
 * The console used to POST credentials to the Gateway's public API,
 * which put administrative identity in the Product Plane.
 *
 * The paths mirror the Gateway's (`/v1/operator/auth/*`) on purpose:
 * the console's migration is then a base-URL change rather than a
 * rewrite of every auth call, which keeps the risky part of this move
 * small.
 */
@Controller('v1/operator/auth')
export class OperatorAuthController {
  private readonly logger = new Logger(OperatorAuthController.name);

  constructor(
    private readonly operators: OperatorRepository,
    private readonly sessions: SessionCacheService,
  ) {}

  /**
   * @Public because this is what a caller uses to OBTAIN a session —
   * requiring one would be circular.
   */
  @Public()
  @Post('login')
  @HttpCode(200)
  async login(
    @Req() request: FastifyRequest,
    @Body() body: LoginBody,
  ): Promise<Record<string, unknown>> {
    const identifier = (body?.identifier ?? '').trim();
    const password = body?.password ?? '';
    if (!identifier || !password) {
      throw new BadRequestException('identifier_and_password_required');
    }

    const operator = await this.operators.authenticate(identifier, password);
    if (operator === null) {
      // One message for every failure: wrong password, unknown user and
      // deactivated account must be indistinguishable, or the form
      // becomes an account-enumeration oracle.
      this.logger.warn(`login failed for identifier=${identifier}`);
      throw new UnauthorizedException('invalid_credentials');
    }

    const session = await this.operators.issueSession(operator, {
      userAgent: headerValue(request.headers['user-agent']),
      ip: request.ip ?? null,
    });
    this.logger.log(`login ok: ${operator.username} (${operator.role})`);

    return {
      session_token: session.token,
      expires_at: session.expiresAt.toISOString(),
      operator: toDto(operator, session.expiresAt),
    };
  }

  /**
   * Resolve the bearer session. The console calls this to learn who the
   * cookie belongs to.
   */
  @Get('me')
  async me(@Req() request: RequestWithIdentity): Promise<Record<string, unknown>> {
    const identity = request[IDENTITY_REQUEST_KEY];
    if (!identity) {
      throw new UnauthorizedException('operator_session_required');
    }
    return { operator: toDto(identity.operator, identity.expiresAt) };
  }

  @Post('logout')
  @HttpCode(204)
  async logout(@Req() request: RequestWithIdentity): Promise<void> {
    const token = bearer(request);
    if (!token) {
      return;
    }
    await this.operators.revokeSession(token);
    // Revoking in the database is not enough on its own: the resolution
    // cache would keep answering for up to SESSION_CACHE_TTL_SECONDS,
    // so a logged-out operator stayed authenticated for another 30s.
    // Caught by an end-to-end logout test, not by any unit test —
    // revocation and caching are correct in isolation.
    this.sessions.invalidate(token);
  }
}

function toDto(
  operator: {
    id: string;
    username: string;
    email: string;
    displayName: string;
    role: string;
    permissions: string[];
  },
  expiresAt: Date,
): Record<string, unknown> {
  return {
    id: operator.id,
    username: operator.username,
    email: operator.email,
    // snake_case because that is the key the console's
    // `GatewayOperatorDTO` already parses. The Control Plane is a new
    // service, so it could have picked either — matching the existing
    // reader keeps the console migration to a base-URL change instead
    // of a parser change, which is the part that would break silently.
    display_name: operator.displayName || operator.username,
    role: operator.role,
    permissions: operator.permissions,
    issued_at: Math.floor(Date.now() / 1000),
    expires_at: Math.floor(expiresAt.getTime() / 1000),
  };
}

export function bearer(request: FastifyRequest): string {
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

function headerValue(raw: string | string[] | undefined): string | null {
  if (Array.isArray(raw)) {
    return raw[0] ?? null;
  }
  return raw ?? null;
}
