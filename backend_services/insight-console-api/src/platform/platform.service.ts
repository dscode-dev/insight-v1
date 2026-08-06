import { Injectable, Logger } from '@nestjs/common';

import { getConfig } from '../config/config';

/**
 * Platform health for the Intelligence plane.
 *
 * insight-context.md v2.0: the Console "nunca acessa diretamente os
 * demais serviços — toda comunicação ocorre através do Insight Control
 * Plane", and the Control Plane's job includes "Comunicação com os
 * serviços internos". The console used to probe Atlas, Explorer, Nexus
 * and the Node Agent itself, from four adapters, which meant it also
 * had to hold their service tokens.
 *
 * Collapsing those into one call here removes ATLAS_INTERNAL_TOKEN and
 * EXPLORER_OPS_TOKEN from the console's environment entirely — the
 * console never again needs a credential for a service it is not
 * supposed to be talking to.
 */

export type HealthState = 'healthy' | 'degraded' | 'unavailable' | 'unknown';

export interface HealthReport {
  readonly health: HealthState;
  readonly version: string | null;
  readonly detail: string;
  readonly activity: Record<string, string | number | null>;
}

export interface PlatformHealth {
  /** Keyed by the console's ServiceRegistry ids. */
  readonly services: Record<string, HealthReport>;
  readonly observedAt: string;
}

const UNKNOWN: HealthReport = {
  health: 'unknown',
  version: null,
  detail: 'not observed',
  activity: {},
};

export function mapHealth(raw: unknown): HealthState {
  const value = String(raw ?? '').toLowerCase();
  if (['up', 'healthy', 'ok', 'ready'].includes(value)) return 'healthy';
  if (value === 'degraded') return 'degraded';
  if (['down', 'unhealthy', 'unavailable', 'unreachable'].includes(value)) {
    return 'unavailable';
  }
  return 'unknown';
}

interface Probe {
  readonly id: string;
  readonly url: string;
  readonly headers: Record<string, string>;
  readonly read: (body: unknown, status: number) => HealthReport;
}

@Injectable()
export class PlatformService {
  private readonly logger = new Logger(PlatformService.name);

  async health(): Promise<PlatformHealth> {
    const probes = this.probes();
    const results = await Promise.all(
      probes.map(async (probe) => {
        // Each probe is failure-isolated: one unreachable service must
        // report as unavailable, not blank the whole dashboard.
        try {
          const response = await fetch(probe.url, {
            headers: { Accept: 'application/json', ...probe.headers },
            signal: AbortSignal.timeout(getConfig().UPSTREAM_TIMEOUT_MS),
          });
          const body = await response.json().catch(() => null);
          return [probe.id, probe.read(body, response.status)] as const;
        } catch (error) {
          const detail =
            error instanceof Error ? error.message : 'probe failed';
          this.logger.warn(`${probe.id} probe failed: ${detail}`);
          return [
            probe.id,
            { ...UNKNOWN, health: 'unavailable' as const, detail },
          ] as const;
        }
      }),
    );

    return {
      services: Object.fromEntries(results),
      observedAt: new Date().toISOString(),
    };
  }

  private probes(): Probe[] {
    const config = getConfig();
    const list: Probe[] = [
      {
        id: 'atlas',
        url: `${trim(config.ATLAS_API_BASE_URL)}/health`,
        headers: config.ATLAS_INTERNAL_TOKEN
          ? { 'X-Internal-Token': config.ATLAS_INTERNAL_TOKEN }
          : {},
        read: (body, status) => {
          const raw = (body as { status?: string } | null)?.status;
          return {
            health: status === 200 ? mapHealth(raw) : 'unavailable',
            version: '1.0.0',
            detail: `atlas ${raw ?? status}`,
            activity: {},
          };
        },
      },
      {
        id: 'explorer',
        url: `${trim(config.EXPLORER_API_BASE_URL)}/health`,
        headers: config.EXPLORER_OPS_TOKEN
          ? { 'X-Ops-Token': config.EXPLORER_OPS_TOKEN }
          : {},
        read: (body, status) => {
          const raw = (body as { status?: string } | null)?.status;
          return {
            health: status === 200 ? mapHealth(raw ?? 'ok') : 'unavailable',
            version: null,
            detail: `explorer ${raw ?? status}`,
            activity: {},
          };
        },
      },
    ];

    if (config.NEXUS_API_BASE_URL) {
      list.push({
        id: 'nexus',
        url: `${trim(config.NEXUS_API_BASE_URL)}/healthz`,
        headers: {},
        read: (body, status) => {
          const raw = (body as { status?: string } | null)?.status;
          return {
            health: status === 200 ? mapHealth(raw ?? 'ok') : 'unavailable',
            version: null,
            detail: `nexus ${raw ?? status}`,
            activity: {},
          };
        },
      });
    }

    // Anvil now runs alongside Atlas on this host (moved off the cloud),
    // so the Control Plane can probe it directly instead of inferring
    // its state from the Gateway's platform-health aggregate.
    if (config.ANVIL_API_BASE_URL) {
      list.push({
        id: 'anvil',
        url: `${trim(config.ANVIL_API_BASE_URL)}/live`,
        headers: {},
        read: (_body, status) => ({
          health: status === 200 ? 'healthy' : 'unavailable',
          version: null,
          detail: `anvil ${status}`,
          activity: {},
        }),
      });
    }

    return list;
  }
}

function trim(value: string): string {
  return value.replace(/\/+$/, '');
}
