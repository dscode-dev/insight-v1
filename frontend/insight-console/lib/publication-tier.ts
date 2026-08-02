// Publication-control tier mapping — Sprint 4.5 Part 14.
//
// PURE module (no server imports). It consumes Gateway-issued permissions
// only. It must never map role names to permissions or grant authority from
// local role ownership.
//
//   viewer       — sees everything, mutates nothing
//   admin        — reviews tickets, manages agents
//   super_admin  — admin + persona editing + manual publication

import type { ConsoleOperator } from "@/types/auth";

export type PublicationTier = "viewer" | "admin" | "super_admin";

const TIER_RANK: Record<PublicationTier, number> = {
  viewer: 0,
  admin: 1,
  super_admin: 2,
};

export function publicationTier(
  operator: ConsoleOperator | null | undefined,
): PublicationTier {
  if (!operator) return "viewer";
  const permissions = new Set(operator.permissions);
  if (permissions.has("config.write") || permissions.has("flag.write")) {
    return "super_admin";
  }
  if (
    permissions.has("dlq.replay") ||
    permissions.has("scheduler.force_sync") ||
    permissions.has("feed.delete")
  ) {
    return "admin";
  }
  return "viewer";
}

/** True when `tier` is at least `min`. */
export function tierAtLeast(tier: PublicationTier, min: PublicationTier): boolean {
  return TIER_RANK[tier] >= TIER_RANK[min];
}

/** True when the operator's tier is at least `tier`. */
export function hasTier(
  operator: ConsoleOperator | null | undefined,
  tier: PublicationTier,
): boolean {
  return tierAtLeast(publicationTier(operator), tier);
}
