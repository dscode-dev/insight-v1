// Auth + RBAC contract.
//
// IMPORTANT: Gateway owns operator identity, sessions, roles and
// permissions. The Console receives the operator contract from
// /v1/operator/auth/me and uses Permission as a type-safe string literal
// for UI affordance checks; it does NOT grant rights.
//
// Every UI permission check is a hint — the BFF re-validates against
// the same operator session on every mutating call. A frontend that
// bypasses the hint cannot escalate because the BFF rejects the
// underlying call.

/** Role labels are rendered from Gateway-owned operator identity. */
export type Role =
  | "SuperAdmin"
  | "PlatformAdmin"
  | "Operations"
  | "Support"
  | "MLAdmin"
  | "Moderator"
  | "ReadOnly";

/**
 * Granular permission slugs. Frontend uses these for UI affordances
 * (hide a button, dim a row); the BFF re-checks on every call.
 *
 * New permissions are added by extending this union AND wiring the
 * backend check; the frontend can never grant a permission the
 * backend doesn't issue.
 */
export type Permission =
  // Users
  | "user.read"
  | "user.suspend"
  | "user.ban"
  | "user.shadow_ban"
  | "user.force_logout"
  | "user.invalidate_sessions"
  | "user.change_permissions"
  | "user.flag_for_audit"
  | "user.add_notes"
  // Feed moderation
  | "feed.read"
  | "feed.hide"
  | "feed.delete"
  | "feed.restore"
  | "feed.mark_sensitive"
  // Scheduler
  | "scheduler.read"
  | "scheduler.pause"
  | "scheduler.resume"
  | "scheduler.force_sync"
  // Providers
  | "provider.read"
  | "provider.enable"
  | "provider.disable"
  | "provider.maintenance"
  | "provider.force_sync"
  // Atlas / ML
  | "model.read"
  | "model.promote"
  | "model.rollback"
  | "model.pause_consumer"
  | "model.resume_consumer"
  | "model.enable_family"
  | "model.disable_family"
  | "model.clear_cache"
  // DLQ
  | "dlq.read"
  | "dlq.replay"
  | "dlq.archive"
  | "dlq.mark_resolved"
  // Audit
  | "audit.read"
  // Feature flags
  | "flag.read"
  | "flag.write"
  // Configuration
  | "config.read"
  | "config.write"
  // Platform-level
  | "maintenance_mode.toggle"
  | "incident.manage"
  | "console.access";

export interface ConsoleOperator {
  /** Stable operator id (UUID). */
  id: string;
  /** Display name; surfaces in audit events as the actor. */
  displayName: string;
  /** Username — primary administrative identity owned by Gateway. */
  username?: string;
  /** Email — administrative identity / contact. */
  email?: string;
  /** E.164 phone — legacy gateway identity (optional under password auth). */
  phone?: string;
  /** Role resolved by Gateway for the current operator session. */
  role: Role;
  /**
   * Full permission set the BFF granted this session. The frontend
   * checks against this via `hasPermission()` to render or hide
   * affordances; the BFF re-checks every mutation.
   */
  permissions: Permission[];
  /** Reserved for future Gateway session metadata. */
  issuedAt: number;
  /** Reserved for future Gateway session metadata. */
  expiresAt: number;
}

/**
 * Type-safe permission check. Returns false for unknown permissions
 * — the operator NEVER has more than the backend granted.
 */
export function hasPermission(
  operator: ConsoleOperator | null | undefined,
  perm: Permission,
): boolean {
  if (!operator) return false;
  return operator.permissions.includes(perm);
}
