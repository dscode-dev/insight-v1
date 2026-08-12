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
  // Applying a finished collection to Atlas: rebuilds the similarity corpus
  // and re-encodes it into pgvector. On the runtime router, not the internal
  // read one — it is an action with an effect, not a projection.
  'vector-memory',
]);

/**
 * Atlas's ingestion surface, which lives under `/v1/intake/*` — a third
 * prefix, alongside `/atlas/*` and `/v1/internal/intelligence/*`.
 *
 * Listed rather than pattern-matched for the same reason the other two lists
 * are: this is an allow-list, and a prefix rule would let a path nobody
 * reviewed through the moment Atlas grows a route under /v1/intake.
 */
const ATLAS_QUERY_ROOTS = new Set([
  '',            // POST — a consulta em si
  'categorias',  // GET  — as cinco lentes e a pergunta de cada uma
  // GET — quanto cada lente vale EM CADA COMPETIÇÃO, e onde nunca foi medida.
  // Separado de `categorias` porque a validade não é propriedade da lente:
  // `gols` mede +5,8% na Premier League e −5,8% no Brasileirão.
  'validacao',
]);

const ATLAS_INTAKE_ROOTS = new Set([
  'matches',     // POST — ingere um lote (aceita ?simular=true)
  'contract',    // GET  — o contrato vigente e um exemplo válido
  'coverage',    // GET  — o que o Atlas tem, por competição e temporada
  'rejections',  // GET  — as últimas recusas, com o motivo
  'conflicts',   // GET  — desacordos entre fontes sobre o mesmo fato
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

    // `atlas/query/*` -> `v1/query/*`. Terceiro prefixo do Atlas, ao lado
    // de /atlas/* e /v1/internal/intelligence/*; mesmo motivo do intake.
    if (root === 'query') {
      const leaf = firstSegment(rest.slice('query'.length).replace(/^\/+/, ''));
      if (!ATLAS_QUERY_ROOTS.has(leaf)) {
        return { kind: 'refuse', reason: 'unknown_atlas_query_path' };
      }
      return {
        kind: 'allow',
        upstream: 'atlas',
        path: leaf ? `v1/query/${leaf}` : 'v1/query',
      };
    }

    // `atlas/intake/*` -> `v1/intake/*`. Checked before the two-way split
    // below because the ingestion surface is neither of those routers.
    if (root === 'intake') {
      const leaf = firstSegment(rest.slice('intake/'.length));
      if (!ATLAS_INTAKE_ROOTS.has(leaf)) {
        return { kind: 'refuse', reason: 'unknown_atlas_intake_path' };
      }
      return { kind: 'allow', upstream: 'atlas', path: `v1/intake/${leaf}` };
    }

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
