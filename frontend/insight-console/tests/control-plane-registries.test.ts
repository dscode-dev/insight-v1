// CONSOLE-FOUNDATION-A — registry tests.

import { beforeEach, describe, expect, it } from "vitest";

import { __resetControlPlaneConfig } from "@/lib/control-plane/config";
import { EnvironmentRegistry } from "@/lib/control-plane/registries/environments";
import { ServiceRegistry } from "@/lib/control-plane/registries/services";
import { CapabilityRegistry } from "@/lib/control-plane/registries/capabilities";

beforeEach(() => {
  __resetControlPlaneConfig();
  delete process.env.ATLAS_API_BASE_URL;
  delete process.env.NEXUS_API_BASE_URL;
});

describe("EnvironmentRegistry", () => {
  it("resolves the two confirmed environments", () => {
    const envs = EnvironmentRegistry.list();
    expect(envs.map((e) => e.id).sort()).toEqual(["google-cloud", "robozao"]);
    expect(EnvironmentRegistry.get("robozao")?.displayName).toBe("Robozão");
  });

  it("rejects unknown / injection-shaped ids", () => {
    expect(EnvironmentRegistry.get("http://evil")).toBeNull();
    expect(EnvironmentRegistry.isValidId("../../etc")).toBe(false);
  });

  it("public serialization carries no URLs or secrets", () => {
    const json = JSON.stringify(EnvironmentRegistry.list());
    expect(json).not.toMatch(/http:\/\/|https:\/\/|token/i);
    expect(EnvironmentRegistry.get("robozao")?.serviceIds).toContain("atlas");
  });
});

describe("ServiceRegistry", () => {
  it("looks up a real service and filters by environment", () => {
    expect(ServiceRegistry.get("atlas")?.environmentId).toBe("robozao");
    const cloud = ServiceRegistry.list({ environment: "google-cloud" });
    expect(cloud.every((s) => s.environmentId === "google-cloud")).toBe(true);
    expect(cloud.map((s) => s.id)).toContain("social");
  });

  it("distinguishes configured from unavailable (Nexus unset ⇒ not configured)", () => {
    __resetControlPlaneConfig();
    expect(ServiceRegistry.get("nexus")?.configured).toBe(false);
    process.env.ATLAS_API_BASE_URL = "http://atlas:8085";
    __resetControlPlaneConfig();
    expect(ServiceRegistry.get("atlas")?.configured).toBe(true);
  });

  it("never invents services and never serializes endpoints", () => {
    const ids = ServiceRegistry.list().map((s) => s.id);
    // Exactly the confirmed live topology (16 services).
    expect(ids).toHaveLength(16);
    expect(ServiceRegistry.get("made-up-service")).toBeNull();
    expect(JSON.stringify(ServiceRegistry.list())).not.toMatch(/8085|8090|8095|baseUrl|endpointKey|token/);
  });
});

describe("CapabilityRegistry", () => {
  it("registers only evidence-backed capabilities in domain.resource.action form", () => {
    const caps = CapabilityRegistry.list();
    expect(caps.length).toBeGreaterThan(0);
    for (const c of caps) {
      expect(c.id.split(".")).toHaveLength(3);
      expect(c.evidence.length).toBeGreaterThan(0);
    }
  });

  it("classifies read vs mutation and marks mutation approval", () => {
    const mod = CapabilityRegistry.get("social.content.moderate");
    expect(mod?.actionType).toBe("mutation");
    expect(mod?.approvalRequired).toBe(true);
    expect(CapabilityRegistry.get("atlas.intelligence.read")?.actionType).toBe("read");
  });

  it("does not invent a capability without evidence", () => {
    expect(CapabilityRegistry.get("social.users.delete")).toBeNull();
    expect(CapabilityRegistry.isValidId("atlas.detectors.retrain")).toBe(false);
  });
});
