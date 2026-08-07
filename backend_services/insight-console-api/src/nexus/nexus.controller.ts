import {
  All,
  BadRequestException,
  Body,
  Controller,
  Req,
} from '@nestjs/common';
import type { FastifyRequest } from 'fastify';

import {
  IDENTITY_REQUEST_KEY,
  RequestWithIdentity,
} from '../identity/identity.guard';
import { permissionsForRole } from '../identity/rbac';
import { UpstreamService } from '../upstream/upstream.service';
import { classify } from './path-policy';

/**
 * Insight Nexus surfaces, forwarded.
 *
 * Nexus's admin API was unreachable: it authenticated operators against the
 * public Gateway, which `insight-context.md` v2.0 says is not responsible for
 * operators. With no Gateway identity URL configured it answered 503 to
 * everything, so the console had no Nexus screens at all.
 *
 * The hop is now the same one the Node Agent speaks: a service-to-service
 * token plus the operator this service already authenticated.
 *
 * WHY THE PERMISSIONS TRAVEL. Explorer and Atlas trust their shared token for
 * authorization and take the actor as attribution. Nexus checks each route
 * against the operator's permissions, so it needs them — and it denies a
 * request that arrives without any, rather than treating an absent header as
 * unrestricted.
 */
@Controller('nexus')
export class NexusController {
  constructor(private readonly upstream: UpstreamService) {}

  @All('*')
  async forward(
    @Req() request: RequestWithIdentity,
    @Body() body: unknown,
  ): Promise<unknown> {
    const identity = request[IDENTITY_REQUEST_KEY];
    const operator = identity?.operator;
    if (!operator?.id) {
      // The global guard fills this before any handler runs; empty means it
      // was bypassed. Nexus writes the actor into its own immutable audit
      // log, and an unattributed mutation is worse than a refused one.
      throw new BadRequestException('operator_identity_missing');
    }

    const raw = pathAfter(request, '/nexus/');
    const decision = classify(raw, request.method);
    if (decision.kind === 'refuse') {
      throw new BadRequestException(decision.reason);
    }

    const method = request.method.toUpperCase();
    const hasBody = method !== 'GET' && method !== 'DELETE' && method !== 'HEAD';

    return this.upstream.nexus({
      path: decision.path + queryOf(request),
      method,
      body: hasBody ? (body ?? {}) : undefined,
      operator: {
        id: operator.id,
        username: operator.username,
        role: operator.role,
        // Resolved HERE, from the role this service owns. Forwarding a
        // permission list the request supplied would let the caller widen
        // its own authority.
        permissions: permissionsForRole(operator.role),
      },
    });
  }
}

function pathAfter(request: FastifyRequest, marker: string): string {
  const url = request.url ?? '';
  const withoutQuery = url.split('?')[0] ?? '';
  const index = withoutQuery.indexOf(marker);
  if (index < 0) return '';
  return decodeURIComponent(withoutQuery.slice(index + marker.length));
}

function queryOf(request: FastifyRequest): string {
  const url = request.url ?? '';
  const index = url.indexOf('?');
  return index < 0 ? '' : url.slice(index);
}
