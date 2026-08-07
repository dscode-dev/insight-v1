import {
  All,
  BadRequestException,
  Body,
  Controller,
  Req,
} from '@nestjs/common';
import type { FastifyRequest } from 'fastify';

import { getConfig } from '../config/config';
import {
  IDENTITY_REQUEST_KEY,
  RequestWithIdentity,
} from '../identity/identity.guard';
import { UpstreamError } from '../upstream/upstream.service';
import { classifySocialPath } from './social-path-policy';

/**
 * Insight Social's administrative surface, forwarded.
 *
 * REPLACES A HOP. The console used to reach Social as
 * Console → Control Plane → Gateway `/v1/console/social/*` → Social. Per
 * insight-context.md v2.0 the Gateway is not responsible for administration,
 * operators or the console, and the Control Plane is the service that talks to
 * the rest of the platform. The Gateway is now out of this path, and with it
 * the reason for the Gateway to hold Social's operations token.
 *
 * TWO CREDENTIALS, TWO QUESTIONS. `SOCIAL_OPS_TOKEN` proves the CALLER is the
 * Control Plane. The operator headers say WHO asked. Social requires the first
 * on every route and the second on mutations, and it writes the second into
 * its audit trail — a token alone would attribute every ban and suspension to
 * "the Control Plane".
 *
 * Social is in Google Cloud and this service is on the Robozão, so the hop
 * crosses the public internet until the WireGuard tunnel the architecture
 * document calls for exists. That is why the ingress on the other side
 * terminates TLS and allow-lists this host's address, and why the token is
 * long-lived-secret grade rather than a convenience string.
 */
@Controller('social')
export class SocialController {
  @All('*')
  async forward(
    @Req() request: RequestWithIdentity,
    @Body() body: unknown,
  ): Promise<unknown> {
    const identity = request[IDENTITY_REQUEST_KEY];
    const operator = identity?.operator;
    if (!operator?.id) {
      throw new BadRequestException('operator_identity_missing');
    }

    const config = getConfig();
    if (!config.SOCIAL_CONSOLE_BASE_URL || !config.SOCIAL_OPS_TOKEN) {
      // Not configured is not the same as broken. 503 with a named reason
      // lets the console render "unavailable" instead of a blank screen.
      throw new UpstreamError(503, 'social_console_not_configured');
    }

    const raw = pathAfter(request, '/social/');
    const decision = classifySocialPath(raw, request.method);
    if (decision.kind === 'refuse') {
      throw new BadRequestException(decision.reason);
    }

    const method = request.method.toUpperCase();
    const hasBody = method !== 'GET' && method !== 'HEAD' && method !== 'DELETE';
    const url = `${config.SOCIAL_CONSOLE_BASE_URL.replace(/\/+$/, '')}/console/social${
      decision.path
    }${queryOf(request)}`;

    const response = await fetch(url, {
      method,
      signal: AbortSignal.timeout(config.UPSTREAM_TIMEOUT_MS),
      headers: {
        Accept: 'application/json',
        ...(hasBody ? { 'Content-Type': 'application/json' } : {}),
        'X-Ops-Token': config.SOCIAL_OPS_TOKEN,
        // Who is acting. Social refuses a mutation without it, and records it.
        'X-Operator-Id': operator.id,
        'X-Operator': operator.username,
        ...(headerValue(request.headers['x-request-id'])
          ? { 'X-Request-Id': headerValue(request.headers['x-request-id'])! }
          : {}),
      },
      body: hasBody ? JSON.stringify(body ?? {}) : undefined,
    });

    const text = await response.text();
    if (!response.ok) {
      // Preserve the status. Collapsing a 404 for a missing user into a 500
      // would read as an outage of the whole screen.
      throw new UpstreamError(
        response.status,
        `social ${method} ${decision.path} failed with ${response.status}`,
      );
    }
    return text === '' ? {} : (JSON.parse(text) as unknown);
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
