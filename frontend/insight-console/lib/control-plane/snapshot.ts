// Platform Snapshot Service (CONSOLE-FOUNDATION-A, Stage 6/7). SERVER-OWNED.
//
// Assembles the canonical, normalized operational snapshot of the distributed
// platform from the registries + typed adapters. THIS is where platform truth is
// assembled — not the browser. Failures are isolated per adapter; the snapshot
// returns honest partial state (never a fake healthy, never []/{}/0 for an error).
//
// Concurrency: all upstream probes run in parallel (bounded — 5 fixed adapters),
// each with its own timeout. Adapters never throw; they return AdapterResult with
// source attribution either way, so one slow/broken service cannot block or
// collapse the snapshot.

import type { AdapterContext, HealthReport } from "@/lib/control-plane/adapters/base";
import { AtlasAdapter } from "@/lib/control-plane/adapters/atlas";
import { ExplorerAdapter } from "@/lib/control-plane/adapters/explorer";
import { GatewayAdapter } from "@/lib/control-plane/adapters/gateway";
import { NexusAdapter } from "@/lib/control-plane/adapters/nexus";
import { RobozaoAdapter } from "@/lib/control-plane/adapters/robozao";
import { observe } from "@/lib/control-plane/observability";
import { EnvironmentRegistry } from "@/lib/control-plane/registries/environments";
import {
  CapabilityRegistry,
  effectiveState,
} from "@/lib/control-plane/registries/capabilities";
import { ServiceRegistry } from "@/lib/control-plane/registries/services";
import type {
  CapabilityState,
  HealthState,
  PlatformSnapshot,
  ServicePublic,
  ServiceSnapshot,
  SourceStatus,
} from "@/lib/control-plane/types";

interface ResolvedHealth {
  report: HealthReport;
  source: SourceStatus;
}

function syntheticSource(
  service: string,
  environment: ServicePublic["environmentId"],
  state: SourceStatus["state"],
): SourceStatus {
  return { service, environment, state, observedAt: new Date().toISOString(), latencyMs: null, stale: false };
}

const UNKNOWN_REPORT: HealthReport = { health: "unknown", version: null, detail: "not observed", activity: {} };

const ALL_STATES: CapabilityState[] = [
  "DECLARED", "DISCOVERED", "AVAILABLE", "DEGRADED", "UNAVAILABLE", "UNSUPPORTED",
];

export const PlatformSnapshotService = {
  async generate(ctx: AdapterContext): Promise<PlatformSnapshot> {
    const environments = EnvironmentRegistry.list();
    const services = ServiceRegistry.list();

    // Fire the fixed set of adapters in parallel; each is failure-isolated.
    const [atlasR, explorerR, nexusR, cloudR, roboR] = await Promise.all([
      AtlasAdapter.readHealth(ctx),
      ExplorerAdapter.readHealth(ctx),
      NexusAdapter.readHealth(ctx),
      GatewayAdapter.readCloud(ctx),
      RobozaoAdapter.readOperations(ctx),
    ]);

    const sources: SourceStatus[] = [atlasR.source, explorerR.source, nexusR.source, cloudR.source, roboR.source];
    const resolved = new Map<string, ResolvedHealth>();

    // Direct-adapter services (authoritative for their own health).
    if (atlasR.ok) resolved.set("atlas", { report: atlasR.value, source: atlasR.source });
    else resolved.set("atlas", { report: { ...UNKNOWN_REPORT, health: "unavailable", detail: atlasR.error.message }, source: atlasR.source });

    if (explorerR.ok) resolved.set("explorer", { report: explorerR.value, source: explorerR.source });
    else resolved.set("explorer", { report: { ...UNKNOWN_REPORT, health: "unavailable", detail: explorerR.error.message }, source: explorerR.source });

    if (nexusR.ok) resolved.set("nexus", { report: nexusR.value, source: nexusR.source });
    else resolved.set("nexus", { report: { ...UNKNOWN_REPORT, detail: nexusR.error.message }, source: nexusR.source });

    // Cloud services via the gateway platform-health probe.
    const cloudObserved = ["social", "anvil", "cloud-postgres", "cloud-redis", "cloud-clickhouse"];
    if (cloudR.ok) {
      resolved.set("gateway", { report: cloudR.value.self, source: cloudR.source });
      for (const id of cloudObserved) {
        const rep = cloudR.value.services[id];
        // In-map ⇒ real health; absent ⇒ honestly unknown (not down).
        resolved.set(id, { report: rep ?? UNKNOWN_REPORT, source: cloudR.source });
      }
    } else {
      // Gateway unreachable ⇒ gateway itself unavailable; its dependents unknown.
      resolved.set("gateway", { report: { ...UNKNOWN_REPORT, health: "unavailable", detail: cloudR.error.message }, source: cloudR.source });
      for (const id of cloudObserved) resolved.set(id, { report: UNKNOWN_REPORT, source: cloudR.source });
    }

    // Robozão gateway self.
    if (roboR.ok) resolved.set("robozao-gateway", { report: roboR.value.self, source: roboR.source });
    else resolved.set("robozao-gateway", { report: { ...UNKNOWN_REPORT, health: "unavailable", detail: roboR.error.message }, source: roboR.source });

    // Console self (we are serving this request).
    resolved.set("console", {
      report: { health: "healthy", version: null, detail: "serving operators", activity: {} },
      source: syntheticSource("console", "robozao", "available"),
    });

    // Build the per-service snapshots.
    const serviceSnapshots: ServiceSnapshot[] = services.map((svc): ServiceSnapshot => {
      const r = resolved.get(svc.id);
      if (r) {
        return {
          service: svc,
          health: r.report.health,
          version: r.report.version,
          detail: r.report.detail,
          source: r.source,
          activity: r.report.activity,
        };
      }
      // No probe available for this service (e.g. sport-hub, datastores, nginx).
      // Honest: unknown health, "unsupported" source (Console has no probe).
      return {
        service: svc,
        health: "unknown" as HealthState,
        version: null,
        detail: svc.observable ? "not observed" : "no console probe",
        source: syntheticSource(svc.id, svc.environmentId, "unsupported"),
        activity: {},
      };
    });

    // Capability effective states from live service health.
    const healthByService = new Map<string, HealthState>(
      serviceSnapshots.map((s) => [s.service.id, s.health]),
    );
    const byState = Object.fromEntries(ALL_STATES.map((s) => [s, 0])) as Record<CapabilityState, number>;
    let capTotal = 0;
    for (const cap of CapabilityRegistry.descriptors()) {
      const state = effectiveState(cap, healthByService.get(cap.serviceId));
      byState[state] += 1;
      capTotal += 1;
    }

    const partial = sources.some((s) => s.state !== "available");
    observe(partial ? "platform_snapshot_partial" : "platform_snapshot_generated", {
      sources: sources.length,
      degradedSources: sources.filter((s) => s.state !== "available").length,
      correlationId: ctx.correlationId ?? undefined,
    });

    return {
      generatedAt: new Date().toISOString(),
      partial,
      environments,
      services: serviceSnapshots,
      capabilities: { total: capTotal, byState },
      sources,
    };
  },
};
