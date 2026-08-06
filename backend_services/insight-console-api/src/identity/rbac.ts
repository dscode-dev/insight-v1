/**
 * Role → permission resolution. Owned by the Control Plane.
 *
 * insight-context.md v2.0 puts RBAC on the Control Plane. Until now the
 * Gateway derived these (internal/interfaces/http/operator/handlers.go,
 * `permissionsForRole`) and the console consumed whatever it was sent.
 *
 * This mirrors that mapping deliberately: moving WHERE authorization is
 * decided is already a large change, and altering WHAT it decides at
 * the same time would make any behavioural difference impossible to
 * attribute. Widening or narrowing a role is a separate, reviewable
 * change on top of this.
 */

export type Role =
  | 'SuperAdmin'
  | 'PlatformAdmin'
  | 'Operations'
  | 'Support'
  | 'MLAdmin'
  | 'Moderator'
  | 'ReadOnly';

export const ROLES: readonly Role[] = [
  'SuperAdmin',
  'PlatformAdmin',
  'Operations',
  'Support',
  'MLAdmin',
  'Moderator',
  'ReadOnly',
];

/** Everything any role can hold. Read-only baseline for every operator. */
const READ: readonly string[] = [
  'console.access',
  'feed.read',
  'user.read',
  'model.read',
  'dlq.read',
  'audit.read',
  'flag.read',
  'config.read',
  'scheduler.read',
];

const ALL: readonly string[] = [
  ...READ,
  'user.suspend',
  'user.ban',
  'user.shadow_ban',
  'user.force_logout',
  'user.invalidate_sessions',
  'user.change_permissions',
  'user.flag_for_audit',
  'user.add_notes',
  'feed.hide',
  'feed.delete',
  'feed.restore',
  'feed.mark_sensitive',
  'scheduler.pause',
  'scheduler.resume',
  'scheduler.force_sync',
  'provider.read',
  'provider.enable',
  'provider.disable',
  'provider.maintenance',
  'provider.force_sync',
  'model.promote',
  'model.rollback',
  'model.pause_consumer',
  'model.resume_consumer',
  'model.enable_family',
  'model.disable_family',
  'model.clear_cache',
  'dlq.replay',
  'dlq.archive',
  'dlq.mark_resolved',
  'flag.write',
  'config.write',
  'maintenance_mode.toggle',
  'incident.manage',
];

const BY_ROLE: Record<Role, readonly string[]> = {
  SuperAdmin: ALL,
  // The Gateway normalised PlatformAdmin onto SuperAdmin; kept so the
  // move does not quietly demote anybody mid-migration.
  PlatformAdmin: ALL,
  Operations: [
    ...READ,
    'incident.manage',
    'scheduler.pause',
    'scheduler.resume',
    'scheduler.force_sync',
    'provider.enable',
    'provider.disable',
    'dlq.replay',
  ],
  Support: [...READ, 'user.add_notes', 'user.flag_for_audit'],
  Moderator: [
    ...READ,
    'feed.hide',
    'feed.delete',
    'feed.restore',
    'feed.mark_sensitive',
    'user.suspend',
    'user.flag_for_audit',
  ],
  MLAdmin: [
    ...READ,
    'model.promote',
    'model.rollback',
    'model.pause_consumer',
    'model.resume_consumer',
    'model.enable_family',
    'model.disable_family',
    'model.clear_cache',
    // The Quality Gate's promotion decision is gated on config.write
    // (see the console's quality-gate route), so an MLAdmin who cannot
    // write config could not approve a promotion — the one action the
    // role exists for.
    'config.write',
  ],
  ReadOnly: READ,
};

export function isRole(value: string): value is Role {
  return (ROLES as readonly string[]).includes(value);
}

/**
 * Normalises the legacy role spellings the Gateway accepted, so
 * operators created before this migration still resolve.
 */
export function normalizeRole(raw: string): Role {
  switch (raw) {
    case 'super_admin':
      return 'SuperAdmin';
    case 'admin':
      return 'Operations';
    case 'operator':
      return 'Support';
    default:
      return isRole(raw) ? raw : 'ReadOnly';
  }
}

/**
 * Permissions for a role. Unknown roles resolve to the read-only set,
 * never to an empty one: an operator with no `console.access` cannot
 * even load the console, which looks like an outage rather than a
 * misconfigured role.
 */
export function permissionsForRole(raw: string): string[] {
  return [...BY_ROLE[normalizeRole(raw)]];
}
