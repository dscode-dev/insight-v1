/**
 * Which Nexus paths the console may reach, and nothing else.
 *
 * Same shape as `data-intelligence/path-policy.ts` and
 * `product-plane/gateway-path-policy.ts`: a closed allow-list, default-deny.
 * Forwarding commands is not the same as being an open proxy, and a
 * deny-list is never finished.
 *
 * Matching is on the FIRST SEGMENT, never on a string prefix — `agentsX/`
 * is not `agents`, and a prefix check would let it through.
 */

export type NexusDecision =
  | { readonly kind: 'allow'; readonly path: string }
  | { readonly kind: 'refuse'; readonly reason: string };

/**
 * Read surfaces. Every one of these backs something the operator can see.
 */
const READ_ROOTS = new Set<string>([
  'agents',
  'publications',
  'publication-decisions',
  'trend-clusters',
  'narrative-health',
  'drafts',
  'personas',
  'llm',
  'audit',
  'dlq',
]);

/**
 * Writes, listed one by one rather than by root.
 *
 * A root-level allow would have let `POST /v1/agents` through as soon as it
 * existed, without anyone deciding that the console should be able to create
 * an agent. Enumerating means a new mutation is a deliberate addition here.
 */
const WRITES = new Set<string>([
  'POST /v1/agents',
  'PUT /v1/agents/*',
  'POST /v1/agents/*/enable',
  'POST /v1/agents/*/disable',
  'PATCH /v1/publications/tickets/*',
  'POST /v1/publications/tickets/*/publish',
  'POST /v1/publications/manual',
  'PUT /v1/personas/*',
  'POST /v1/audit/events',
  'POST /v1/dlq/trends/*/replay',
]);

const READ_METHODS = new Set(['GET', 'HEAD']);

export function classify(rawPath: string, method: string): NexusDecision {
  const path = rawPath.trim();
  if (path === '') {
    return { kind: 'refuse', reason: 'empty_nexus_path' };
  }
  // `..` would climb out of the prefix the allow-list just approved, which
  // makes every check above it meaningless.
  if (path.includes('..')) {
    return { kind: 'refuse', reason: 'traversal_in_nexus_path' };
  }

  const segments = path.split('/').filter((s) => s !== '');
  // Everything administrative on Nexus lives under /v1. Requiring it here
  // means the probe endpoints (/live, /metrics) are unreachable through the
  // console — they are for the platform, not for an operator.
  if (segments[0] !== 'v1') {
    return { kind: 'refuse', reason: 'unknown_nexus_path' };
  }
  const root = segments[1];
  if (root === undefined || !READ_ROOTS.has(root)) {
    return { kind: 'refuse', reason: 'unknown_nexus_path' };
  }

  const upper = method.toUpperCase();
  if (READ_METHODS.has(upper)) {
    return { kind: 'allow', path: `/${segments.join('/')}` };
  }
  if (WRITES.has(`${upper} ${templateOf(segments)}`)) {
    return { kind: 'allow', path: `/${segments.join('/')}` };
  }
  return {
    kind: 'refuse',
    reason: `unsupported_nexus_write:${upper} /${segments.join('/')}`,
  };
}

/**
 * Collapse concrete ids to `*`, the placeholder the write list uses.
 *
 * Every segment that is not a known literal becomes `*` — a single
 * placeholder, with no attempt to tell a uuid from a slug. Guessing which
 * one a segment is would make the allow-list depend on the SHAPE of a value
 * an operator supplies, and a persona slug that happened to look like a uuid
 * would stop matching.
 *
 * The literals are exactly the words that appear inside an allowed path.
 * Anything else in that position is data.
 */
const PATH_LITERALS = new Set<string>([
  'v1',
  'agents',
  'publications',
  'tickets',
  'manual',
  'personas',
  'audit',
  'events',
  'dlq',
  'trends',
  'replay',
  'enable',
  'disable',
  'publish',
]);

function templateOf(segments: readonly string[]): string {
  const parts = segments.map((s) => (PATH_LITERALS.has(s) ? s : '*'));
  return `/${parts.join('/')}`;
}
