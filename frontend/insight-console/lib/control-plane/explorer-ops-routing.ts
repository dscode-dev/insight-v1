// Which Explorer ops paths are governed mutations. SERVER-ONLY.
//
// Same role — and same fail-closed rule — as `quality-gate-routing.ts`:
// this classification decides whether a write takes the audited path or
// the ordinary one, and a misclassification is silent (the request
// succeeds either way, just without a trail).
//
// The line drawn here is "does this change durable state a human is
// accountable for?":
//
//   GOVERNED  review/promote, review/reject — a curator's verdict on a
//             record. Promotion appends the envelope to the VALIDATED
//             lake layer, which Atlas's StrengthSyncWatcher consumes,
//             so a promotion propagates into Atlas's team ratings.
//             That is an accountable act, not a refresh.
//   GOVERNED  scheduler/cancel — stops every running collection job.
//   ORDINARY  review/replay, jobs/task/*, scheduler/pause|resume,
//             runtime/reload — operational steering. They re-run or
//             pause work; they do not decide what is true.

export type ExplorerOpsRoute =
  | { kind: "governed"; capability: string; resourceType: string }
  | { kind: "ordinary" }
  | { kind: "refuse"; reason: string };

/**
 * Exact paths that must be audited. An exact-match set rather than a
 * pattern: the governed surface is small and closed, and a pattern is
 * how a future path quietly acquires or loses governance.
 */
const GOVERNED: Record<string, { capability: string; resourceType: string }> = {
  "review/promote": {
    capability: "explorer.curation.decide",
    resourceType: "review_record",
  },
  "review/reject": {
    capability: "explorer.curation.decide",
    resourceType: "review_record",
  },
  "scheduler/cancel": {
    capability: "explorer.scheduler.control",
    resourceType: "scheduler",
  },
};

/** Writes that are known-ordinary. Anything unlisted is refused. */
const ORDINARY = new Set([
  "review/replay",
  "jobs/task/start",
  "jobs/task/restart",
  "scheduler/pause",
  "scheduler/resume",
  "runtime/reload",
]);

export function classifyExplorerOpsWrite(path: string): ExplorerOpsRoute {
  const normalized = path.replace(/^\/+|\/+$/g, "");

  const governed = GOVERNED[normalized];
  if (governed) {
    return { kind: "governed", ...governed };
  }
  if (ORDINARY.has(normalized)) {
    return { kind: "ordinary" };
  }
  // DEFAULT DENY. An unrecognised write is refused rather than
  // forwarded as ordinary — otherwise a new Explorer mutation becomes
  // reachable through this proxy, unaudited, the moment it exists
  // upstream, with nothing on the console side to notice.
  return { kind: "refuse", reason: "unknown_explorer_ops_write" };
}
