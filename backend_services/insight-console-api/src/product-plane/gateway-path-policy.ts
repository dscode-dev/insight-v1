/**
 * Which cloud-Gateway paths the Control Plane will forward.
 *
 * The Product plane (Gateway, Social) lives in the cloud and the console
 * must not reach it directly — insight-context.md v2.0 routes everything
 * through the Control Plane. Forwarding is not proxying, so this is a
 * closed allow-list and anything unrecognised is refused.
 *
 * Prefix-matched because these surfaces are id-bearing
 * (`/v1/console/social/users/{id}`) and listing every variant is not
 * possible.
 */

const ALLOWED_PREFIXES = [
  // Administrative surfaces the console's screens use.
  '/v1/console/admin/operators',
  '/v1/console/admin/sessions',
  '/v1/console/admin/users',
  // Social read plane + enforcement (console-owned moderation).
  '/v1/console/social/',
  // Operational identity / delegation.
  '/v1/console/identity',
  // Product-plane health aggregate (social, cloud datastores).
  '/v1/console/platform/health',
  // Legacy moderation action surface.
  '/v1/admin/moderation/',
] as const;

export type GatewayDecision =
  | { readonly kind: 'allow'; readonly path: string }
  | { readonly kind: 'refuse'; readonly reason: string };

export function classifyGatewayPath(rawPath: string): GatewayDecision {
  const withoutQuery = rawPath.split('?')[0] ?? '';
  const path = withoutQuery.startsWith('/') ? withoutQuery : `/${withoutQuery}`;

  // `..` would climb out of the prefix the allow-list just approved,
  // which is the entire point of having one.
  if (path.includes('..')) {
    return { kind: 'refuse', reason: 'path_traversal' };
  }
  // A double slash can normalise differently upstream than it does
  // here, so the prefix this matched may not be the prefix reached.
  if (path.includes('//')) {
    return { kind: 'refuse', reason: 'ambiguous_path' };
  }

  for (const prefix of ALLOWED_PREFIXES) {
    if (!path.startsWith(prefix)) {
      continue;
    }
    // An exact-match entry must not also match `<prefix>something`:
    // `/v1/console/admin/operatorsX` is not `/v1/console/admin/operators`.
    if (
      !prefix.endsWith('/') &&
      path.length > prefix.length &&
      path[prefix.length] !== '/'
    ) {
      continue;
    }
    return { kind: 'allow', path };
  }
  return { kind: 'refuse', reason: 'unknown_gateway_path' };
}
