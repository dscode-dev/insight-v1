// Service Registry (CONSOLE-FOUNDATION-A, Stage 2). SERVER-OWNED, config-backed.
//
// Persistence decision: a code+config registry (NO database). The service set is
// deployment topology, not user data; it changes with releases, not at runtime;
// and it must be validated/reviewed. A DB would add operational surface without
// benefit for V1. `configured` is derived from validated env (config.ts); the
// public read model strips all endpoints/tokens.
//
// The seed is EXACTLY the CONSOLE-ARCHITECTURE-A confirmed live topology (16
// containers across 2 environments). No invented services.

import { controlPlaneConfig } from "@/lib/control-plane/config";
import type {
  AdapterKind,
  ServiceDescriptor,
  ServicePublic,
} from "@/lib/control-plane/types";

// Internal seed. `endpointKey` names the config upstream (never inlined here).
type Seed = Omit<ServiceDescriptor, "capabilities"> & {
  /** Which config upstream (if any) resolves this service's Console endpoint. */
  readonly endpointKey: keyof ReturnType<typeof controlPlaneConfig> | null;
  readonly capabilities: string[];
};

const SEED: readonly Seed[] = [
  // ---- Robozão ----
  {
    id: "console", displayName: "Insight Console", domain: "platform",
    environmentId: "robozao", serviceType: "next.js", ownership: "platform",
    protocol: "http", adapterKind: "none", observable: true, mutable: false,
    dependencies: ["gateway", "atlas", "explorer", "robozao-gateway"],
    lifecycle: "active", endpointKey: null, capabilities: [],
  },
  {
    id: "atlas", displayName: "Insight Atlas", domain: "intelligence",
    environmentId: "robozao", serviceType: "python/fastapi", ownership: "intelligence",
    protocol: "http", adapterKind: "atlas", observable: true, mutable: false,
    dependencies: ["postgres", "redis"], lifecycle: "frozen", endpointKey: "atlas",
    capabilities: ["atlas.health.read", "atlas.intelligence.read", "atlas.replay.read"],
  },
  {
    id: "explorer", displayName: "Insight Explorer", domain: "data",
    environmentId: "robozao", serviceType: "python/fastapi", ownership: "data",
    protocol: "http", adapterKind: "explorer", observable: true, mutable: false,
    dependencies: ["postgres", "redis", "atlas"], lifecycle: "active", endpointKey: "explorer",
    capabilities: ["explorer.health.read", "explorer.missions.read", "explorer.datasets.read"],
  },
  {
    id: "robozao-gateway", displayName: "Robozão Gateway", domain: "gateway",
    environmentId: "robozao", serviceType: "go", ownership: "platform",
    protocol: "gateway", adapterKind: "robozao", observable: true, mutable: false,
    dependencies: ["explorer", "atlas"], lifecycle: "active", endpointKey: "robozaoGateway",
    capabilities: ["robozao.operations.read"],
  },
  {
    id: "nexus", displayName: "Insight Nexus", domain: "publication",
    environmentId: "robozao", serviceType: "go", ownership: "publication",
    protocol: "http", adapterKind: "nexus", observable: true, mutable: false,
    dependencies: ["qwen", "postgres"], lifecycle: "active", endpointKey: "nexus",
    capabilities: ["nexus.publications.read"],
  },
  {
    id: "sport-hub", displayName: "Sport Hub", domain: "data",
    environmentId: "robozao", serviceType: "service", ownership: "data",
    protocol: "http", adapterKind: "none", observable: false, mutable: false,
    dependencies: [], lifecycle: "active", endpointKey: null, capabilities: [],
  },
  {
    id: "postgres", displayName: "PostgreSQL (pgvector)", domain: "platform",
    environmentId: "robozao", serviceType: "postgres-16", ownership: "platform",
    protocol: "worker", adapterKind: "none", observable: false, mutable: false,
    dependencies: [], lifecycle: "active", endpointKey: null, capabilities: [],
  },
  {
    id: "redis", displayName: "Redis", domain: "platform",
    environmentId: "robozao", serviceType: "redis-7", ownership: "platform",
    protocol: "worker", adapterKind: "none", observable: false, mutable: false,
    dependencies: [], lifecycle: "active", endpointKey: null, capabilities: [],
  },
  {
    id: "qwen", displayName: "Qwen Runtime", domain: "publication",
    environmentId: "robozao", serviceType: "ollama", ownership: "publication",
    protocol: "worker", adapterKind: "none", observable: false, mutable: false,
    dependencies: [], lifecycle: "active", endpointKey: null, capabilities: [],
  },
  // ---- Google Cloud ----
  {
    id: "gateway", displayName: "Insight Gateway", domain: "gateway",
    environmentId: "google-cloud", serviceType: "go", ownership: "platform",
    protocol: "gateway", adapterKind: "gateway", observable: true, mutable: false,
    dependencies: ["social", "anvil", "cloud-postgres", "cloud-redis"], lifecycle: "active",
    endpointKey: "gateway",
    capabilities: [
      "gateway.platform_health.read", "gateway.audit.read",
      "gateway.users.read", "social.moderation.read", "social.content.moderate",
      "trust.report.read", "trust.moderation.read", "audit.event.read",
      // CONSOLE-SOCIAL-B report lifecycle transitions (Gateway-owned reports):
      "trust.report.review", "trust.report.resolve", "trust.report.dismiss",
    ],
  },
  {
    id: "social", displayName: "Insight Social", domain: "social",
    environmentId: "google-cloud", serviceType: "go/grpc", ownership: "social",
    protocol: "grpc", adapterKind: "gateway", observable: true, mutable: false,
    dependencies: ["cloud-postgres", "cloud-redis"], lifecycle: "active", endpointKey: null,
    capabilities: [
      "social.agents.read", "social.users.read",
      "social.overview.read", "social.activity.read", "social.user.read",
      "social.agent.read", "social.post.read", "social.comment.read",
      "social.community.read", "social.relationship.read", "social.boost.read",
      "social.save.read", "social.investigation.read",
      // CONSOLE-SOCIAL-B enforcement plane (operator-driven mutations):
      "social.user.suspend", "social.user.ban",
      "social.content.hide", "social.content.restore",
      "social.agent.deactivate", "social.agent.reactivate",
    ],
  },
  {
    id: "anvil", displayName: "Insight Anvil", domain: "analytics",
    environmentId: "google-cloud", serviceType: "python/worker", ownership: "analytics",
    protocol: "worker", adapterKind: "gateway", observable: true, mutable: false,
    dependencies: ["cloud-clickhouse"], lifecycle: "active", endpointKey: null, capabilities: [],
  },
  {
    id: "cloud-postgres", displayName: "Cloud PostgreSQL", domain: "platform",
    environmentId: "google-cloud", serviceType: "postgres-16", ownership: "platform",
    protocol: "worker", adapterKind: "gateway", observable: true, mutable: false,
    dependencies: [], lifecycle: "active", endpointKey: null, capabilities: [],
  },
  {
    id: "cloud-redis", displayName: "Cloud Redis", domain: "platform",
    environmentId: "google-cloud", serviceType: "redis-7", ownership: "platform",
    protocol: "worker", adapterKind: "gateway", observable: true, mutable: false,
    dependencies: [], lifecycle: "active", endpointKey: null, capabilities: [],
  },
  {
    id: "cloud-clickhouse", displayName: "Cloud ClickHouse", domain: "analytics",
    environmentId: "google-cloud", serviceType: "clickhouse-24", ownership: "analytics",
    protocol: "worker", adapterKind: "gateway", observable: true, mutable: false,
    dependencies: [], lifecycle: "active", endpointKey: null, capabilities: [],
  },
  {
    id: "cloud-nginx", displayName: "Cloud Edge (nginx)", domain: "gateway",
    environmentId: "google-cloud", serviceType: "nginx", ownership: "platform",
    protocol: "http", adapterKind: "none", observable: false, mutable: false,
    dependencies: ["gateway"], lifecycle: "active", endpointKey: null, capabilities: [],
  },
];

const BY_ID = new Map<string, Seed>(SEED.map((s) => [s.id, s]));

/** Is this service configured — i.e. does the Console have a usable endpoint? */
export function isServiceConfigured(seed: Seed): boolean {
  if (seed.endpointKey === null) {
    // Not directly reachable by the Console. "Observed via gateway" services are
    // considered configured iff the gateway itself is configured.
    if (seed.adapterKind === "gateway") return controlPlaneConfig().gateway.configured;
    return false;
  }
  const upstream = controlPlaneConfig()[seed.endpointKey];
  return typeof upstream === "object" && upstream !== null && "configured" in upstream
    ? (upstream as { configured: boolean }).configured
    : false;
}

/** INTERNAL: full descriptors incl. adapter wiring (no endpoints inlined). */
export function listServiceDescriptors(): ServiceDescriptor[] {
  return SEED.map((s) => {
    const { endpointKey: _endpointKey, ...rest } = s;
    void _endpointKey;
    return { ...rest };
  });
}

/** INTERNAL: the seed (with endpointKey) for adapters/snapshot use. */
export function getServiceSeed(id: string): Seed | null {
  return BY_ID.get(id) ?? null;
}

function toPublic(seed: Seed): ServicePublic {
  const { endpointKey: _k, ...rest } = seed;
  void _k;
  return { ...rest, configured: isServiceConfigured(seed) };
}

export interface ServiceFilter {
  environment?: string;
  domain?: string;
  adapterKind?: AdapterKind;
}

export const ServiceRegistry = {
  list(filter: ServiceFilter = {}): ServicePublic[] {
    return SEED.filter((s) => {
      if (filter.environment && s.environmentId !== filter.environment) return false;
      if (filter.domain && s.domain !== filter.domain) return false;
      if (filter.adapterKind && s.adapterKind !== filter.adapterKind) return false;
      return true;
    }).map(toPublic);
  },
  get(id: string): ServicePublic | null {
    const seed = BY_ID.get(id);
    return seed ? toPublic(seed) : null;
  },
  isValidId(id: string): boolean {
    return BY_ID.has(id);
  },
};
