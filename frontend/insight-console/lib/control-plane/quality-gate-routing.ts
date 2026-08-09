// Which Quality Gate paths are governed mutations. SERVER-ONLY.
//
// Extracted from the route handler so it can be tested directly: this
// single classification decides whether a request takes the governed
// path (capability → authorize → audit intent → mutate → audit outcome)
// or the ordinary one. Getting it wrong means a promotion decision
// recorded in Atlas with NO console-side capability check and NO audit
// trail — silently, because the request would still succeed.
//
// FAILS CLOSED. A path that looks like a decision write but does not
// parse cleanly is REFUSED, never demoted to the ungoverned branch:
// demoting it would still forward the write upstream, which is exactly
// the outcome this classification exists to prevent.

export type QualityGateRoute =
  | { kind: "governed"; executionId: string }
  | { kind: "ordinary" }
  | { kind: "refuse"; reason: string };

const DECISION_SUFFIX = "/decision";
const DECISION_PATH = /^replays\/([^/]+)\/decision$/;

export function classifyQualityGateWrite(path: string): QualityGateRoute {
  if (!path.endsWith(DECISION_SUFFIX)) {
    return { kind: "ordinary" };
  }

  // From here on the request WILL reach a decision endpoint upstream,
  // so every remaining branch is either governed or refused.
  const match = DECISION_PATH.exec(path);
  if (!match) {
    return { kind: "refuse", reason: "malformed_decision_path" };
  }

  let executionId: string;
  try {
    executionId = decodeURIComponent(match[1]!);
  } catch {
    // A malformed percent-escape throws; treating it as ordinary would
    // forward an unaudited write.
    return { kind: "refuse", reason: "malformed_decision_path" };
  }

  // An id that decodes to contain a separator could reshape the
  // upstream path after this check has already passed.
  if (executionId.trim().length === 0 || executionId.includes("/")) {
    return { kind: "refuse", reason: "malformed_decision_path" };
  }

  return { kind: "governed", executionId };
}
