/**
 * Which Node Agent paths the console may reach, and nothing else.
 *
 * WHY THIS EXISTS. The console had `lib/robozao.ts`, a direct adapter to the
 * Node Agent with `http://robozao-gateway:8095` baked in as a default. Seven
 * API routes used it. That is exactly what insight-context.md v2.0 rules out —
 * "O Console nunca acessa diretamente os demais serviços" — and it was the
 * last such route left after Fase B moved the other twelve.
 *
 * It also made a claim in the deployment untrue. The console container holds
 * no service credential, which is usually read as "it cannot reach anything
 * else". For the Node Agent it could: the address was a compiled-in default,
 * not configuration, so removing the variable changed nothing.
 *
 * Same shape as the other classifiers: closed allow-list, first-segment
 * matching, default-deny.
 */

export type NodeAgentDecision =
  | { readonly kind: 'allow'; readonly path: string }
  | { readonly kind: 'refuse'; readonly reason: string };

/** Read surfaces backing the operations screens. */
const READ_ROOTS = new Set<string>([
  'operations',
  'vpn',
  'v1',
]);

/**
 * Writes, enumerated rather than allowed by root.
 *
 * `/operations/commands` creates a typed, audited command on the node. It is
 * listed one by one so a new mutation on the Node Agent is a deliberate
 * addition here, not something a route rename unlocks.
 */
const WRITES = new Set<string>([
  'POST /operations/commands',
  'POST /operations/commands/*/approve',
  'POST /operations/incidents',
  'POST /operations/incidents/*/*',
]);

const READ_METHODS = new Set(['GET', 'HEAD']);

/** Segments that are literal parts of an allowed path; anything else is data. */
const PATH_LITERALS = new Set<string>([
  'operations',
  'commands',
  'incidents',
  'approve',
  'v1',
  'registry',
  'vpn',
  'status',
]);

export function classifyNodeAgentPath(
  rawPath: string,
  method: string,
): NodeAgentDecision {
  const path = rawPath.trim();
  if (path === '') {
    return { kind: 'refuse', reason: 'empty_node_agent_path' };
  }
  if (path.includes('..')) {
    return { kind: 'refuse', reason: 'traversal_in_node_agent_path' };
  }

  const segments = path.split('/').filter((s) => s !== '');
  const root = segments[0];
  if (root === undefined || !READ_ROOTS.has(root)) {
    return { kind: 'refuse', reason: 'unknown_node_agent_path' };
  }

  const upper = method.toUpperCase();
  if (READ_METHODS.has(upper)) {
    return { kind: 'allow', path: `/${segments.join('/')}` };
  }

  // Ingestion endpoints (POST /operations/events, /tickets, /runs,
  // /datasets) are for SERVICES reporting their own work, authenticated with
  // OPS_INGEST_TOKEN. An operator posting through the console would forge a
  // service's history, so they are deliberately not in the write list.
  const template = `/${segments
    .map((s) => (PATH_LITERALS.has(s) ? s : '*'))
    .join('/')}`;
  if (WRITES.has(`${upper} ${template}`)) {
    return { kind: 'allow', path: `/${segments.join('/')}` };
  }
  return {
    kind: 'refuse',
    reason: `unsupported_node_agent_write:${upper} /${segments.join('/')}`,
  };
}
