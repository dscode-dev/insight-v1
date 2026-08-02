// Sprint 4.5 Part 14 — publication tier consumes Gateway-issued permissions.

import { describe, expect, it } from "vitest";

import {
  hasTier,
  publicationTier,
  tierAtLeast,
} from "@/lib/publication-tier";
import type { ConsoleOperator, Permission } from "@/types/auth";

function operator(permissions: Permission[]): ConsoleOperator {
  return {
    id: "op-1",
    displayName: "Test Operator",
    phone: "+5511999999999",
    role: "ReadOnly",
    permissions,
    issuedAt: 0,
    expiresAt: 0,
  };
}

describe("publicationTier", () => {
  it.each([
    [["console.access"], "viewer"],
    [["console.access", "dlq.replay"], "admin"],
    [["console.access", "scheduler.force_sync"], "admin"],
    [["console.access", "feed.delete"], "admin"],
    [["console.access", "config.write"], "super_admin"],
    [["console.access", "flag.write"], "super_admin"],
  ] as Array<[Permission[], string]>)("%j → %s", (permissions, tier) => {
    expect(publicationTier(operator(permissions))).toBe(tier);
  });

  it("null operator is a viewer (never escalates)", () => {
    expect(publicationTier(null)).toBe("viewer");
    expect(publicationTier(undefined)).toBe("viewer");
  });
});

describe("tier ordering", () => {
  it("higher tiers imply lower ones", () => {
    expect(tierAtLeast("super_admin", "admin")).toBe(true);
    expect(tierAtLeast("super_admin", "viewer")).toBe(true);
    expect(tierAtLeast("admin", "viewer")).toBe(true);
  });

  it("lower tiers never satisfy higher bars", () => {
    expect(tierAtLeast("viewer", "admin")).toBe(false);
    expect(tierAtLeast("viewer", "super_admin")).toBe(false);
    expect(tierAtLeast("admin", "super_admin")).toBe(false);
  });

  it("hasTier gates mutations: viewer cannot review, admin cannot edit personas", () => {
    expect(hasTier(operator(["console.access"]), "admin")).toBe(false);
    expect(hasTier(operator(["console.access", "dlq.replay"]), "admin")).toBe(true);
    expect(hasTier(operator(["console.access", "dlq.replay"]), "super_admin")).toBe(false);
    expect(hasTier(operator(["console.access", "config.write"]), "super_admin")).toBe(true);
    expect(hasTier(null, "viewer")).toBe(true); // read-only floor
  });
});
