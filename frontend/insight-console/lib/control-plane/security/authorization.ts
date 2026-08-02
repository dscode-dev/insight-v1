// Capability authorization seam (CONSOLE-SECURITY-A0, Stage 5). SERVER-ONLY.
//
// Authorization is a DECISION, not a registry lookup. The Capability Registry is
// descriptive (does this capability exist?); it MUST NOT grant a right. This seam
// reuses the platform's REAL rules — the SuperAdmin bypass and the granular
// permission set the Gateway issues — and invents no permissions.
//
// The real SuperAdmin rule is the one already present in the codebase
// (lib/operations-domain.ts: `role === "SuperAdmin" || permissions.includes(...)`
// and Gateway console/roles.go). It is preserved here explicitly + documented.

import { CapabilityRegistry } from "@/lib/control-plane/registries/capabilities";
import type { Permission } from "@/types/auth";
import type { OperatorContext } from "@/lib/control-plane/security/operator-context";

export interface AuthorizationTarget {
  readonly environmentId?: string | null;
  readonly serviceId?: string | null;
  readonly resourceType?: string | null;
  readonly resourceId?: string | null;
}

export type AuthorizationReason =
  | "allowed_superadmin"
  | "allowed_permission"
  | "denied_permission_missing"
  | "denied_no_policy"
  | "denied_capability_unsupported";

export type PolicySource = "role:SuperAdmin" | `permission:${string}` | "none";

export interface AuthorizationDecision {
  readonly allowed: boolean;
  readonly decision: "allow" | "deny";
  readonly reasonCode: AuthorizationReason;
  readonly policySource: PolicySource;
  readonly capability: string;
  readonly requiredPermission: Permission | null;
  readonly target: AuthorizationTarget;
  readonly evaluatedAt: string;
}

function decision(
  partial: Omit<AuthorizationDecision, "decision" | "allowed" | "evaluatedAt"> & { allowed: boolean },
): AuthorizationDecision {
  return {
    ...partial,
    decision: partial.allowed ? "allow" : "deny",
    evaluatedAt: new Date().toISOString(),
  };
}

/**
 * Authorize an operator to perform `capability` (optionally gated by a
 * `requiredPermission` derived by the caller from the REAL per-action policy,
 * e.g. moderation ACTION_PERMISSION). Fail-closed.
 */
export function authorize(
  operator: OperatorContext,
  capability: string,
  requiredPermission: Permission | null,
  target: AuthorizationTarget = {},
): AuthorizationDecision {
  const base = { policySource: "none" as PolicySource, capability, requiredPermission, target };

  // Registry presence is a precondition, NOT authorization.
  if (!CapabilityRegistry.isValidId(capability)) {
    return decision({ ...base, allowed: false, reasonCode: "denied_capability_unsupported" });
  }

  // Real SuperAdmin rule (documented, pre-existing platform policy).
  if (operator.roles.includes("SuperAdmin")) {
    return decision({
      ...base,
      allowed: true,
      reasonCode: "allowed_superadmin",
      policySource: "role:SuperAdmin",
    });
  }

  // A mutation with no declared permission policy is denied (fail-closed) — we
  // never authorize just because the capability exists.
  if (!requiredPermission) {
    return decision({ ...base, allowed: false, reasonCode: "denied_no_policy" });
  }

  if (operator.permissions.includes(requiredPermission)) {
    return decision({
      ...base,
      allowed: true,
      reasonCode: "allowed_permission",
      policySource: `permission:${requiredPermission}`,
    });
  }

  return decision({ ...base, allowed: false, reasonCode: "denied_permission_missing" });
}
