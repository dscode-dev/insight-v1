import { Injectable, Logger } from '@nestjs/common';

import { getConfig } from '../config/config';
import { HealthReport, mapHealth } from './platform.service';

export interface NodeAgentStatus {
  readonly self: HealthReport;
  /** Per-service reports the Node Agent observed on its own machine. */
  readonly services: Record<string, HealthReport>;
}

interface OpsService {
  service_id?: string;
  status?: string;
  identity?: { service_id?: string; version?: string };
  metrics?: { active_jobs?: number; cpu_percent?: number; memory_mb?: number };
  error?: string;
}

/**
 * The Node Agent (Robozão) — machine state for the host it runs on.
 *
 * Reached from the Control Plane, not from the console: per
 * insight-context.md v2.0 the Node Agent sits under the Control Plane in
 * the Intelligence-plane fan-out, and the console talks to nothing
 * directly.
 *
 * The agent authenticates the OPERATOR, so its session token is
 * forwarded rather than a service credential — the Control Plane is
 * acting on a person's behalf here, and the agent's own audit should
 * name that person.
 */
@Injectable()
export class NodeAgentService {
  private readonly logger = new Logger(NodeAgentService.name);

  async status(
    operator: { id?: string; username?: string; role?: string } = {},
  ): Promise<NodeAgentStatus> {
    const config = getConfig();
    const url = `${config.ROBOZAO_GATEWAY_URL.replace(/\/+$/, '')}/operations/status`;

    let payload: { services?: OpsService[] } | null = null;
    try {
      const response = await fetch(url, {
        headers: {
          Accept: 'application/json',
          // Token de SERVIÇO, não a sessão do operador. O Node Agent
          // não revalida identidade — o Control Plane já fez isso, e
          // repassar a sessão dele ao gateway público era o que
          // devolvia 401 em toda chamada.
          'X-Control-Plane-Token': config.NODE_AGENT_TOKEN,
          // Atribuição, para a auditoria do Node Agent nomear a pessoa.
          ...(operator.id ? { 'X-Operator-Id': operator.id } : {}),
          ...(operator.username ? { 'X-Operator': operator.username } : {}),
          ...(operator.role ? { 'X-Operator-Role': operator.role } : {}),
        },
        signal: AbortSignal.timeout(config.UPSTREAM_TIMEOUT_MS),
      });
      if (!response.ok) {
        throw new Error(`node agent responded ${response.status}`);
      }
      payload = (await response.json()) as { services?: OpsService[] };
    } catch (error) {
      const detail = error instanceof Error ? error.message : 'unreachable';
      this.logger.warn(`node agent unreachable: ${detail}`);
      return {
        self: {
          health: 'unavailable',
          version: null,
          detail,
          activity: {},
        },
        // Empty, not "everything is down": the Control Plane cannot see
        // those services through a silent agent, and reporting them
        // down would raise a false incident.
        services: {},
      };
    }

    const services: Record<string, HealthReport> = {};
    for (const row of payload?.services ?? []) {
      const id = row.identity?.service_id ?? row.service_id;
      if (!id) continue;
      const activity: Record<string, string | number | null> = {};
      if (typeof row.metrics?.active_jobs === 'number') {
        activity.active_jobs = row.metrics.active_jobs;
      }
      if (typeof row.metrics?.cpu_percent === 'number') {
        activity.cpu_percent = row.metrics.cpu_percent;
      }
      services[id] = {
        health: mapHealth(row.status),
        version:
          typeof row.identity?.version === 'string'
            ? row.identity.version
            : null,
        detail: row.error ? row.error : `${row.status ?? 'unknown'}`,
        activity,
      };
    }

    return {
      self: {
        health: 'healthy',
        version: null,
        detail: 'operations status served',
        activity: {},
      },
      services,
    };
  }
}
