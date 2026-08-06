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
import { UpstreamError, UpstreamService } from '../upstream/upstream.service';
import { classify } from './path-policy';

/**
 * Data Intelligence surfaces (Explorer + Atlas), forwarded.
 *
 * The console's `lib/data-intelligence.ts` used to call both services
 * directly, which meant it held EXPLORER_OPS_TOKEN and
 * ATLAS_INTERNAL_TOKEN. insight-context.md v2.0 routes all of this
 * through the Control Plane, so the tokens live here and the console
 * holds none.
 *
 * Every path is classified against a closed allow-list first — see
 * path-policy.ts. This forwards commands; it is not an open proxy.
 */
@Controller('data-intelligence')
export class DataIntelligenceController {
  constructor(private readonly upstream: UpstreamService) {}

  @All('*')
  async forward(
    @Req() request: RequestWithIdentity,
    @Body() body: unknown,
  ): Promise<unknown> {
    const identity = request[IDENTITY_REQUEST_KEY];
    const actor = identity?.operator.username || identity?.operator.id || '';
    if (!actor) {
      // The global guard fills this before any handler runs; empty means
      // it was bypassed. Explorer records the actor in its own audit log,
      // and an unattributed mutation is worse than a refused one.
      throw new BadRequestException('operator_identity_missing');
    }

    const raw = pathAfter(request, '/data-intelligence/');
    const decision = classify(raw, request.method);
    if (decision.kind === 'refuse') {
      throw new BadRequestException(decision.reason);
    }

    const search = queryOf(request);
    const method = request.method.toUpperCase();
    const hasBody = method !== 'GET' && method !== 'DELETE';

    try {
      if (decision.upstream === 'atlas') {
        return await this.upstream.atlas({
          path: decision.path + search,
          method,
          body: hasBody ? (body ?? {}) : undefined,
          actor,
        });
      }
      return await this.upstream.explorer({
        // `explorer()` prefixes /explorer/ itself.
        path: decision.path + search,
        method,
        body: hasBody ? (body ?? {}) : undefined,
        actor,
        correlationId: headerValue(request.headers['x-request-id']),
      });
    } catch (error) {
      if (error instanceof UpstreamError) {
        // Preserve the upstream status. Collapsing everything to 500
        // would turn a 404 for a missing pipeline into an apparent
        // outage of the whole screen.
        throw error;
      }
      throw error;
    }
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

function headerValue(raw: string | string[] | undefined): string | null {
  if (Array.isArray(raw)) return raw[0] ?? null;
  return raw ?? null;
}
