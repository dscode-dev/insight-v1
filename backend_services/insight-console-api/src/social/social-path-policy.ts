/**
 * Which Social paths the console may reach, and nothing else.
 *
 * WHY THE CONTROL PLANE TALKS TO SOCIAL DIRECTLY. It used to go through the
 * public Gateway: Console → Control Plane → Gateway `/v1/console/social/*` →
 * Social. insight-context.md v2.0 says the Gateway is not responsible for
 * administration, operators or the console, and that the Control Plane is the
 * service that communicates with the rest of the platform. The Gateway hop was
 * a third party in a two-party conversation, and it made the Gateway hold
 * Social's operations token.
 *
 * Same shape as the other classifiers here: closed allow-list, first-segment
 * matching, default-deny. Forwarding administrative commands is not the same
 * as being a proxy in front of a social network.
 */

export type SocialDecision =
  | { readonly kind: 'allow'; readonly path: string }
  | { readonly kind: 'refuse'; readonly reason: string };

/**
 * Read surfaces. Every one backs something an operator can see in the console.
 */
const READ_ROOTS = new Set<string>([
  'overview',
  'activity',
  'users',
  'agents',
  'posts',
  'comments',
  'communities',
  'relationships',
  'boosts',
  'timeline',
  // Subscribed feed sources for Radar. Read returns the key HINT, never the
  // key — the secrecy is enforced on Social's side, not by this list.
  'radar',
  // The competition registry. Social is the source of truth for it
  // platform-wide — the app's rail, the feed's partition, and what the
  // Explorer is permitted to collect all read from here.
  'competitions',
]);

/**
 * Writes, enumerated one by one rather than allowed by root.
 *
 * `users` is readable, and a root-level write allow would have made
 * `DELETE /console/social/users/{id}` reachable the day someone added it.
 * Every mutation against a live social network should be a deliberate line
 * here.
 */
const WRITES = new Set<string>([
  'POST /agents/*/deactivate',
  'POST /agents/*/reactivate',
  // Radar sources. The API key is write-only on Social's side, so PATCH is
  // how a credential is set or rotated and no method can read one back.
  'POST /radar/sources',
  'PATCH /radar/sources/*',
  'DELETE /radar/sources/*',
  // Competition registry. DELETE is allowed because Social refuses it while
  // any post references the competition (the foreign key is ON DELETE
  // RESTRICT) and answers 409 with the count — so the destructive case is
  // already bounded on the far side, and the console can explain it. An
  // operator retiring a competition that HAS history uses PATCH
  // {"active": false}, which hides it without destroying the conversation.
  'POST /competitions',
  'PATCH /competitions/*',
  'DELETE /competitions/*',
]);

const READ_METHODS = new Set(['GET', 'HEAD']);

/** Segments that are literal parts of an allowed path; anything else is data. */
const PATH_LITERALS = new Set<string>([
  ...READ_ROOTS,
  'deactivate',
  'reactivate',
  'sources',
]);

export function classifySocialPath(
  rawPath: string,
  method: string,
): SocialDecision {
  const path = rawPath.trim();
  if (path === '') {
    return { kind: 'refuse', reason: 'empty_social_path' };
  }
  // `..` would climb out of the /console/social/ prefix the ingress routes,
  // which is the boundary keeping the rest of Social's port unreachable.
  if (path.includes('..')) {
    return { kind: 'refuse', reason: 'traversal_in_social_path' };
  }

  const segments = path.split('/').filter((s) => s !== '');
  const root = segments[0];
  if (root === undefined || !READ_ROOTS.has(root)) {
    return { kind: 'refuse', reason: 'unknown_social_path' };
  }

  const upper = method.toUpperCase();
  if (READ_METHODS.has(upper)) {
    return { kind: 'allow', path: `/${segments.join('/')}` };
  }

  const template = `/${segments
    .map((s) => (PATH_LITERALS.has(s) ? s : '*'))
    .join('/')}`;
  if (WRITES.has(`${upper} ${template}`)) {
    return { kind: 'allow', path: `/${segments.join('/')}` };
  }
  return {
    kind: 'refuse',
    reason: `unsupported_social_write:${upper} /${segments.join('/')}`,
  };
}
