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
import { permissionsForRole } from '../identity/rbac';
import { UpstreamError } from '../upstream/upstream.service';
import { classifyNodeAgentPath } from './node-agent-path-policy';

/**
 * Node Agent surfaces, forwarded.
 *
 * Replaces the console's `lib/robozao.ts`, which held the agent's address as a
 * compiled-in default and called it directly. The console now has no route to
 * the Node Agent at all — see node-agent-path-policy.ts for why that mattered
 * even without a credential.
 *
 * The hop carries the SERVICE token plus operator attribution headers. The
 * Node Agent does not re-validate the operator (the Control Plane already
 * did), but it writes the actor into its own audit log, so the name has to
 * travel.
 */
@Controller('node-agent')
export class NodeAgentController {
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
    if (!config.NODE_AGENT_TOKEN) {
      throw new UpstreamError(503, 'node_agent_token_missing');
    }

    const raw = pathAfter(request, '/node-agent/');
    const decision = classifyNodeAgentPath(raw, request.method);
    if (decision.kind === 'refuse') {
      throw new BadRequestException(decision.reason);
    }

    const method = request.method.toUpperCase();
    const hasBody = method !== 'GET' && method !== 'HEAD' && method !== 'DELETE';
    const url = `${config.ROBOZAO_GATEWAY_URL.replace(/\/+$/, '')}${
      decision.path
    }${queryOf(request)}`;

    const response = await fetch(url, {
      method,
      signal: AbortSignal.timeout(config.UPSTREAM_TIMEOUT_MS),
      headers: {
        Accept: 'application/json',
        ...(hasBody ? { 'Content-Type': 'application/json' } : {}),
        'X-Control-Plane-Token': config.NODE_AGENT_TOKEN,
        'X-Operator-Id': operator.id,
        'X-Operator': operator.username,
        'X-Operator-Role': operator.role,
        // Resolved HERE, from the role this service owns — never taken from
        // the request, which would let a caller widen its own authority.
        //
        // Without this header the Node Agent received no permissions at all
        // and refused every command with 403: identity arrived, authorization
        // did not, and the refusal read as "this operator may not" when in
        // fact nobody had been asked.
        'X-Operator-Permissions': permissionsForRole(operator.role).join(','),
        // The Node Agent enforces idempotency on command creation, so the
        // key has to survive the hop or every retry would create a new
        // command.
        ...(headerValue(request.headers['idempotency-key'])
          ? { 'Idempotency-Key': headerValue(request.headers['idempotency-key'])! }
          : {}),
        ...(headerValue(request.headers['x-request-id'])
          ? { 'X-Request-Id': headerValue(request.headers['x-request-id'])! }
          : {}),
      },
      body: hasBody ? JSON.stringify(body ?? {}) : undefined,
    });

    const text = await response.text();
    if (!response.ok) {
      // Preserve the status. Collapsing a 404 for a missing incident into a
      // 500 would read as an outage of the whole screen.
      throw new UpstreamError(
        response.status,
        `node agent ${method} ${decision.path} failed with ${response.status}`,
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
