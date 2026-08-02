// Control Plane domain types (CONSOLE-FOUNDATION-A).
//
// These model the server-owned truth of the distributed platform. Types split
// into INTERNAL descriptors (may hold endpoints — never serialized) and PUBLIC
// read models (safe for the browser). See registries/services.ts.

export type EnvironmentId = "robozao" | "google-cloud";

export type ServiceDomain =
  | "platform"
  | "gateway"
  | "intelligence"
  | "data"
  | "social"
  | "publication"
  | "analytics";

/** Which typed adapter (if any) the Console uses to observe a service. */
export type AdapterKind =
  | "atlas"
  | "explorer"
  | "gateway"
  | "robozao"
  | "nexus"
  | "none";

/** Health is a distinct axis from configured/available. `unknown` ≠ healthy. */
export type HealthState = "healthy" | "degraded" | "unavailable" | "unknown";

/**
 * Per-source outcome for aggregate reads. Distinguishes the failure modes the
 * architecture audit flagged as conflated (DATA_FLOWS DF): a timeout is not an
 * empty dataset; unsupported is not unavailable.
 */
export type SourceState =
  | "available"
  | "degraded"
  | "unavailable"
  | "unsupported"
  | "unauthorized"
  | "timeout"
  | "error"
  | "unknown";

/**
 * Capability reality (ADR-0002 grammar `domain.resource.action`). Semantics:
 *  - DECLARED   config knows this capability should exist for the adapter/service
 *  - DISCOVERED runtime confirmed the upstream surface exists
 *  - AVAILABLE  currently usable
 *  - DEGRADED   exists but partial upstream failure/dependency reduces quality
 *  - UNAVAILABLE exists conceptually but cannot currently be used
 *  - UNSUPPORTED the service does not implement it
 */
export type CapabilityState =
  | "DECLARED"
  | "DISCOVERED"
  | "AVAILABLE"
  | "DEGRADED"
  | "UNAVAILABLE"
  | "UNSUPPORTED";

export type CapabilityClass = "read" | "mutation";
export type RiskLevel = "low" | "medium" | "high" | "critical";

// ---- Environment ----
export interface EnvironmentDescriptor {
  readonly id: EnvironmentId;
  readonly displayName: string;
  readonly type: "on-prem" | "cloud";
  readonly location: string | null;
  readonly active: boolean;
  readonly metadata: Record<string, string>;
}
/** Public read model = descriptor + membership. Contains no URLs/secrets. */
export interface EnvironmentPublic extends EnvironmentDescriptor {
  readonly serviceIds: string[];
}

// ---- Service ----
/** INTERNAL. Holds the resolved endpoint — NEVER serialize this directly. */
export interface ServiceDescriptor {
  readonly id: string;
  readonly displayName: string;
  readonly domain: ServiceDomain;
  readonly environmentId: EnvironmentId;
  readonly serviceType: string;
  readonly ownership: string;
  readonly protocol: "http" | "grpc" | "gateway" | "worker";
  readonly adapterKind: AdapterKind;
  /** Can the Console observe this service (health/reads)? */
  readonly observable: boolean;
  /** Does the Console expose any mutation for it today? (foundation: false) */
  readonly mutable: boolean;
  readonly dependencies: string[];
  readonly capabilities: string[]; // capability ids
  readonly lifecycle: "active" | "frozen" | "deprecated";
}
/** PUBLIC read model. No endpoint, no token. */
export interface ServicePublic {
  readonly id: string;
  readonly displayName: string;
  readonly domain: ServiceDomain;
  readonly environmentId: EnvironmentId;
  readonly serviceType: string;
  readonly ownership: string;
  readonly protocol: ServiceDescriptor["protocol"];
  readonly adapterKind: AdapterKind;
  readonly observable: boolean;
  readonly mutable: boolean;
  readonly dependencies: string[];
  readonly capabilities: string[];
  readonly lifecycle: ServiceDescriptor["lifecycle"];
  /** True when the Console has a usable route+auth to reach it. */
  readonly configured: boolean;
}

// ---- Capability ----
export interface CapabilityDescriptor {
  readonly id: string; // domain.resource.action
  readonly serviceId: string;
  readonly environmentId: EnvironmentId;
  readonly domain: string;
  readonly resource: string;
  readonly action: string;
  readonly actionType: CapabilityClass;
  readonly risk: RiskLevel;
  readonly approvalRequired: boolean;
  /** Baseline declared state; runtime probing may upgrade/downgrade it. */
  readonly declaredState: CapabilityState;
  /** Real backing route/RPC evidence — no capability without evidence. */
  readonly evidence: string;
}
export interface CapabilityPublic extends CapabilityDescriptor {
  /** Effective state after (optional) runtime discovery from a snapshot. */
  readonly state: CapabilityState;
}

// ---- Sources & Snapshot ----
export interface SourceStatus {
  readonly service: string;
  readonly environment: EnvironmentId;
  readonly state: SourceState;
  readonly observedAt: string;
  readonly latencyMs: number | null;
  readonly stale: boolean;
  readonly error?: {
    readonly code: string;
    readonly retryable: boolean;
    readonly message: string;
  };
}

export interface ServiceSnapshot {
  readonly service: ServicePublic;
  readonly health: HealthState;
  readonly version: string | null;
  readonly detail: string;
  readonly source: SourceStatus;
  /** Real, service-reported activity where a contract provides it. Never derived. */
  readonly activity: Record<string, string | number | null>;
}

export interface PlatformSnapshot {
  readonly generatedAt: string;
  /** True when at least one source failed/degraded — honest partial state. */
  readonly partial: boolean;
  readonly environments: EnvironmentPublic[];
  readonly services: ServiceSnapshot[];
  readonly capabilities: {
    readonly total: number;
    readonly byState: Record<CapabilityState, number>;
  };
  readonly sources: SourceStatus[];
}
