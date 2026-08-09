import {
  All,
  BadRequestException,
  Body,
  Controller,
  HttpException,
  Req,
} from '@nestjs/common';
import type { FastifyRequest } from 'fastify';

import { getConfig } from '../config/config';
import {
  IDENTITY_REQUEST_KEY,
  RequestWithIdentity,
} from '../identity/identity.guard';
import { classifyGatewayPath } from './gateway-path-policy';

/**
 * Product-plane surfaces (cloud Gateway → Social), forwarded.
 *
 * The Product plane "nunca possui conhecimento da existência do Console
 * Administrativo", and the console reaches nothing directly, so the
 * Control Plane is the only thing that talks to the cloud Gateway on an
 * operator's behalf. ADMIN_API_INTERNAL_TOKEN therefore lives here and
 * not in the console.
 */
@Controller('product-plane')
export class ProductPlaneController {
  @All('*')
  async forward(
    @Req() request: RequestWithIdentity,
    @Body() body: unknown,
  ): Promise<unknown> {
    const config = getConfig();
    if (!config.ADMIN_API_BASE_URL) {
      throw new HttpException('gateway_not_configured', 503);
    }
    const identity = request[IDENTITY_REQUEST_KEY];
    const actor = identity?.operator.username || identity?.operator.id || '';
    if (!actor) {
      // The global guard fills this before any handler runs; empty means
      // it was bypassed, and an unattributed administrative call is
      // worse than a refused one.
      throw new BadRequestException('operator_identity_missing');
    }

    const decision = classifyGatewayPath(pathAfter(request, '/product-plane/'));
    if (decision.kind === 'refuse') {
      throw new BadRequestException(decision.reason);
    }

    const base = config.ADMIN_API_BASE_URL.replace(/\/+$/, '');
    // The configured base may already end in /v1; joining blindly would
    // produce /v1/v1/....
    const suffix =
      base.endsWith('/v1') && decision.path.startsWith('/v1/')
        ? decision.path.slice(3)
        : decision.path;
    const method = request.method.toUpperCase();
    const hasBody = method !== 'GET' && method !== 'DELETE';

    const response = await fetch(`${base}${suffix}${queryOf(request)}`, {
      method,
      signal: AbortSignal.timeout(config.UPSTREAM_TIMEOUT_MS),
      headers: {
        Accept: 'application/json',
        ...(hasBody ? { 'Content-Type': 'application/json' } : {}),
        ...(config.ADMIN_API_INTERNAL_TOKEN
          ? { 'X-Internal-Token': config.ADMIN_API_INTERNAL_TOKEN }
          : {}),
        // Attribution derives from the session this service resolved.
        'X-Operator': actor,
      },
      body: hasBody ? JSON.stringify(body ?? {}) : undefined,
    });

    const text = await response.text();
    if (!response.ok) {
      // The STATUS is preserved so the console can tell a 403 from a
      // 404 from an outage. The BODY is not echoed: an arbitrary
      // upstream error body can carry internal detail, and this is the
      // boundary between two planes.
      throw new HttpException(
        { code: `gateway_http_${response.status}`, message: 'gateway rejected the request' },
        response.status,
      );
    }
    try {
      return JSON.parse(text) as unknown;
    } catch {
      // 204 and other empty successes.
      return {};
    }
  }
}

function pathAfter(request: FastifyRequest, marker: string): string {
  const url = (request.url ?? '').split('?')[0] ?? '';
  const index = url.indexOf(marker);
  return index < 0 ? '' : decodeURIComponent(url.slice(index + marker.length));
}

function queryOf(request: FastifyRequest): string {
  const url = request.url ?? '';
  const index = url.indexOf('?');
  return index < 0 ? '' : url.slice(index);
}
