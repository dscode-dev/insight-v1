// Platform health, via the Insight Control Plane. SERVER-ONLY.
//
// REPLACES four direct probes. The console used to call Atlas,
// Explorer, Nexus and the Node Agent itself — insight-context.md v2.0
// says it "nunca acessa diretamente os demais serviços; toda
// comunicação ocorre através do Insight Control Plane".
//
// The concrete win beyond conformance: the console no longer needs
// ATLAS_INTERNAL_TOKEN or EXPLORER_OPS_TOKEN in its environment at all.
// It held credentials for services it was not supposed to be talking
// to, and a token that does not exist cannot leak.

import { controlPlaneFetch } from "@/lib/control-plane/adapters/console-api";
import {
  ControlPlaneError,
  codeFromUpstreamStatus,
  normalizeThrown,
  sourceStateForCode,
} from "@/lib/control-plane/errors";
import { readSessionCookie } from "@/lib/session-cookie";
import type { AdapterContext, AdapterResult, HealthReport } from "@/lib/control-plane/adapters/base";
import type { SourceStatus } from "@/lib/control-plane/types";

const OPERATION = "control-plane.platform.health";

export interface PlatformHealthValue {
  /** Per-service reports keyed by ServiceRegistry id. */
  readonly services: Record<string, HealthReport>;
  /** The Node Agent's own report plus what it sees on its machine. */
  readonly nodeAgent: {
    readonly self: HealthReport;
    readonly services: Record<string, HealthReport>;
  };
}

const UNKNOWN: HealthReport = {
  health: "unknown",
  version: null,
  detail: "not observed",
  activity: {},
};

function source(state: SourceStatus["state"], latencyMs: number | null): SourceStatus {
  return {
    service: "control-plane",
    environment: "robozao",
    state,
    observedAt: new Date().toISOString(),
    latencyMs,
    stale: false,
  };
}

export const PlatformAdapter = {
  serviceId: "control-plane" as const,
  environmentId: "robozao" as const,

  async readHealth(ctx: AdapterContext): Promise<AdapterResult<PlatformHealthValue>> {
    const started = Date.now();
    try {
      const res = await controlPlaneFetch("/platform/health", {
        token: ctx.operatorToken ?? readSessionCookie(),
        timeoutMs: ctx.timeoutMs ?? 8000,
      });
      const latency = Date.now() - started;
      if (!res.ok) {
        // Built through the real constructor rather than cast into
        // shape: `as never` on an error object hides a genuine contract
        // mismatch, and the snapshot reads `error.message` to explain
        // an outage to an operator.
        const error = new ControlPlaneError(
          codeFromUpstreamStatus(res.status),
          `control plane responded ${res.status}`,
          {
            service: "control-plane",
            environment: "robozao",
            operation: OPERATION,
            correlationId: ctx.correlationId ?? undefined,
          },
        );
        return {
          ok: false,
          source: source(sourceStateForCode(error.code), latency),
          error,
        };
      }
      const body = (await res.json()) as Partial<PlatformHealthValue>;
      return {
        ok: true,
        source: source("available", latency),
        value: {
          services: body.services ?? {},
          nodeAgent: body.nodeAgent ?? { self: UNKNOWN, services: {} },
        },
      };
    } catch (thrown) {
      const error = normalizeThrown(thrown, {
        service: "control-plane",
        environment: "robozao",
        operation: OPERATION,
        correlationId: ctx.correlationId ?? undefined,
      });
      return {
        ok: false,
        source: source(sourceStateForCode(error.code), Date.now() - started),
        error,
      };
    }
  },
};
