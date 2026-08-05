/**
 * Rejects any request that doesn't carry a valid, fresh, console-signed
 * identity envelope. Applied globally — there is no "public" surface on
 * this service other than /health.
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

import { getConfig } from '../config/config';
import {
  IDENTITY_HEADER,
  IDENTITY_SIGNATURE_HEADER,
  IdentityVerificationError,
  OperatorIdentity,
  verifyIdentity,
} from './operator-identity';
import { IS_PUBLIC_KEY } from './public.decorator';

/** Where the verified identity is parked for controllers to read. */
export const IDENTITY_REQUEST_KEY = 'consoleIdentity';

export interface RequestWithIdentity extends FastifyRequest {
  [IDENTITY_REQUEST_KEY]?: OperatorIdentity;
}

@Injectable()
export class IdentityGuard implements CanActivate {
  private readonly logger = new Logger(IdentityGuard.name);

  constructor(private readonly reflector: Reflector) {}

  canActivate(context: ExecutionContext): boolean {
    const isPublic = this.reflector.getAllAndOverride<boolean>(IS_PUBLIC_KEY, [
      context.getHandler(),
      context.getClass(),
    ]);
    if (isPublic) {
      return true;
    }

    const request = context.switchToHttp().getRequest<RequestWithIdentity>();
    const headers = request.headers;

    try {
      const identity = verifyIdentity(
        headerValue(headers[IDENTITY_HEADER]),
        headerValue(headers[IDENTITY_SIGNATURE_HEADER]),
        getConfig().CONSOLE_API_SIGNING_SECRET,
      );
      request[IDENTITY_REQUEST_KEY] = identity;
      return true;
    } catch (error) {
      // Log the REASON but never the envelope or signature — a rejected
      // envelope may still contain a real operator id, and the signature
      // is a secret-derived value.
      const reason =
        error instanceof IdentityVerificationError ? error.message : 'unexpected';
      this.logger.warn(`identity rejected: ${reason}`);
      throw new UnauthorizedException('console_identity_required');
    }
  }
}

function headerValue(raw: string | string[] | undefined): string | undefined {
  if (Array.isArray(raw)) {
    // A duplicated security header is ambiguous — refuse rather than
    // picking one and hoping.
    return undefined;
  }
  return raw;
}
