// Control Plane public surface (CONSOLE-FOUNDATION-A). SERVER-ONLY.
// Route handlers import from here; the browser never imports this module.

export { controlPlaneConfig } from "@/lib/control-plane/config";
export { EnvironmentRegistry } from "@/lib/control-plane/registries/environments";
export { ServiceRegistry } from "@/lib/control-plane/registries/services";
export { CapabilityRegistry } from "@/lib/control-plane/registries/capabilities";
export { PlatformSnapshotService } from "@/lib/control-plane/snapshot";
export { ControlPlaneError } from "@/lib/control-plane/errors";
export { actorFromOperator, rejectClientAssertedActor } from "@/lib/control-plane/actor";
export type {
  EnvironmentId,
  EnvironmentPublic,
  ServicePublic,
  CapabilityPublic,
  CapabilityState,
  HealthState,
  PlatformSnapshot,
  ServiceSnapshot,
  SourceStatus,
  SourceState,
} from "@/lib/control-plane/types";
