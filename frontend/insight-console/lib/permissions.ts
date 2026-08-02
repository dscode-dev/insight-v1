// Publication-control guards — Sprint 4.5 Part 14. SERVER-ONLY (pulls
// in the session/api-guard chain). The pure tier mapping lives in
// lib/publication-tier.ts so client components can import it.

import { ConsoleApiError } from "@/lib/admin-api";
import { requireOperator } from "@/lib/api-guard";
import {
  hasTier,
  publicationTier,
  type PublicationTier,
} from "@/lib/publication-tier";
import type { ConsoleOperator } from "@/types/auth";

export { hasTier, publicationTier, type PublicationTier };

/**
 * Route-handler guard: resolves the session operator and enforces a
 * minimum tier. Throws ConsoleApiError(403) below the bar — the same
 * contract as requirePermission(), so withApiHandler() shapes it.
 */
export async function requireTier(
  tier: PublicationTier,
): Promise<ConsoleOperator> {
  const op = await requireOperator();
  if (!hasTier(op, tier)) {
    throw new ConsoleApiError(403, "tier_denied", { upstreamCode: tier });
  }
  return op;
}

/**
 * Audit-grade actor string: stable id + human-readable name, e.g.
 * "Daniela S. (3f2a…)". Nexus stores it verbatim on every mutation.
 */
export function actorOf(operator: ConsoleOperator): string {
  return `${operator.displayName} (${operator.id})`;
}
