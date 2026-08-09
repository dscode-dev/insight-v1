/**
 * Which upstream path a Data Intelligence request is allowed to reach.
 *
 * The Control Plane "encaminha comandos" (insight-context.md v2.0) — but
 * forwarding is not proxying. The browser must never be able to choose a
 * host or an arbitrary path, so every request is classified against a
 * closed set of prefixes and anything unrecognised is REFUSED, not
 * passed through. That is the same default-deny rule the Quality Gate
 * and Explorer-ops routes already use on the console side.
 */

export type Upstream = 'explorer' | 'atlas';

export type PathDecision =
  | { readonly kind: 'allow'; readonly upstream: Upstream; readonly path: string }
  | { readonly kind: 'refuse'; readonly reason: string };

/**
 * Explorer surfaces the console's screens actually use. Prefix-matched
 * on the FIRST segment, so `pipelines/{id}/execute` is covered by
 * `pipelines` without listing every id-bearing variant.
 */
const EXPLORER_ROOTS = new Set([
  'data-intelligence',
  'datasets',
  'duplicates',
  'entity-resolution',
  'executions',
  'jobs',
  'pipelines',
  'quality',
  'realtime',
  'review',
  'runtime',
  'scheduler',
  'sources',
  'status',
  'storage',
  'tickets',
  'audit',
  'analytics',
  'metrics',
  'agents',
  'capabilities',
]);

/**
 * Atlas paths that live under `/atlas/*`. Everything else Atlas serves
 * for this screen lives under `/v1/internal/intelligence/*`.
 *
 * This list is verified against atlas/api/routes/intelligence_workspace.py.
 * It once also contained behaviors, patterns, signals, trends, market,
 * uncertainty, memory, head-to-head and team-memory — none of which
 * exist under /atlas, so any screen calling them would have 404'd. No
 * screen did, which is why it went unnoticed; it was a latent trap for
 * the next feature.
 */
const ATLAS_RUNTIME_ROOTS = new Set([
  'conflicts',
  'ingestion',
  'intelligence-graph',
  'reasoning',
]);

function firstSegment(path: string): string {
  return path.split('/')[0] ?? '';
}

export function classify(rawPath: string, method: string): PathDecision {
  // Strip the query before classifying; it is re-attached by the caller.
  const withoutQuery = rawPath.split('?')[0] ?? '';
  const path = withoutQuery.replace(/^\/+|\/+$/g, '');

  if (path === '') {
    return { kind: 'refuse', reason: 'empty_path' };
  }
  // `..` would let a caller climb out of the prefix the allow-list just
  // approved, which is the whole point of having one.
  if (path.includes('..')) {
    return { kind: 'refuse', reason: 'path_traversal' };
  }

  if (path.startsWith('atlas/')) {
    const rest = path.slice('atlas/'.length);
    if (rest === '') {
      return { kind: 'refuse', reason: 'empty_atlas_path' };
    }
    const root = firstSegment(rest);
    // `intelligence` exists on BOTH Atlas routers and is disambiguated
    // only by method: POST /atlas/intelligence (runtime execution) vs
    // GET /v1/internal/intelligence/intelligence (historical read).
    const isRuntimeIntelligence =
      rest === 'intelligence' && method.toUpperCase() === 'POST';
    const runtime =
      ATLAS_RUNTIME_ROOTS.has(root) ||
      isRuntimeIntelligence ||
      rest.startsWith('datasets');
    return {
      kind: 'allow',
      upstream: 'atlas',
      path: runtime ? `atlas/${rest}` : `v1/internal/intelligence/${rest}`,
    };
  }

  if (EXPLORER_ROOTS.has(firstSegment(path))) {
    return { kind: 'allow', upstream: 'explorer', path };
  }

  return { kind: 'refuse', reason: 'unknown_data_intelligence_path' };
}
