// Environment Registry (CONSOLE-FOUNDATION-A, Stage 1). SERVER-OWNED.
//
// Represents the real deployment environments confirmed by CONSOLE-ARCHITECTURE-A
// (two: on-prem Robozão + Google Cloud). No URLs or secrets live in the public
// read model. New environments are added here without page-level changes (ADR-0001).

import type {
  EnvironmentDescriptor,
  EnvironmentId,
  EnvironmentPublic,
} from "@/lib/control-plane/types";
import { listServiceDescriptors } from "@/lib/control-plane/registries/services";

const ENVIRONMENTS: readonly EnvironmentDescriptor[] = [
  {
    id: "robozao",
    displayName: "Robozão",
    type: "on-prem",
    location: "on-prem",
    active: true,
    metadata: { infrastructure: "Docker Compose", role: "intelligence + console host" },
  },
  {
    id: "google-cloud",
    displayName: "Google Cloud",
    type: "cloud",
    location: "us-central1-c",
    active: true,
    metadata: { infrastructure: "Compute Engine VM", role: "identity + social + analytics" },
  },
];

const BY_ID = new Map<EnvironmentId, EnvironmentDescriptor>(
  ENVIRONMENTS.map((e) => [e.id, e]),
);

function toPublic(env: EnvironmentDescriptor): EnvironmentPublic {
  const serviceIds = listServiceDescriptors()
    .filter((s) => s.environmentId === env.id)
    .map((s) => s.id);
  return { ...env, serviceIds };
}

export const EnvironmentRegistry = {
  list(): EnvironmentPublic[] {
    return ENVIRONMENTS.map(toPublic);
  },
  get(id: string): EnvironmentPublic | null {
    const env = BY_ID.get(id as EnvironmentId);
    return env ? toPublic(env) : null;
  },
  /** True for a syntactically + registry-valid environment id. */
  isValidId(id: string): id is EnvironmentId {
    return BY_ID.has(id as EnvironmentId);
  },
};
