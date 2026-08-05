/**
 * Shapes crossing the Quality Gate boundary.
 *
 * Mirrors `atlas/backtest/contracts.py` and `atlas/backtest/approval.py`
 * loosely on purpose: only the fields the console actually renders or
 * sends are declared. Everything else stays `unknown` and is forwarded
 * untouched, so an Atlas-side addition doesn't require a Nest release
 * before it can reach a screen.
 */

export type Verdict = 'approved' | 'rejected';

/** What the operator submits. */
export interface DecisionInput {
  readonly verdict: Verdict;
  readonly reason: string;
  /** Approve despite the gate recommending against it. */
  readonly override_recommendation?: boolean;
  /** Approve a replay that had no baseline to diff against. */
  readonly acknowledge_no_baseline?: boolean;
}

export interface ReplaySubmission {
  readonly source: 'match' | 'competition' | 'season' | 'interval' | 'dataset' | 'mission';
  readonly competition?: string;
  readonly season?: string;
  readonly year?: number;
  readonly uid?: string;
  readonly start?: string;
  readonly end?: string;
}

export interface PromotionRecommendation {
  readonly agent: string;
  readonly trend_type: string;
  readonly verdict: string; // Approved | Warning | Rejected
  readonly reasons: string[];
}

export interface RegressionDiff {
  readonly identical: boolean;
  readonly baseline_hash: string;
  readonly candidate_hash: string;
  readonly new_detections: Record<string, unknown>[];
  readonly lost_detections: Record<string, unknown>[];
  readonly confidence_changes: Record<string, unknown>[];
  readonly strength_changes: Record<string, unknown>[];
  readonly trend_changes: Record<string, unknown>[];
}

export interface RegressionReport {
  readonly quality_regression: boolean;
  readonly confidence_regression: boolean;
  readonly detector_regression: boolean;
  readonly trend_regression: boolean;
  readonly similarity_regression: boolean;
  readonly reasoning_regression: boolean;
  readonly diff: RegressionDiff;
}

export interface QualityEvaluation {
  readonly replay_hash: string;
  readonly promotions: PromotionRecommendation[];
  readonly regression: RegressionReport | null;
  readonly [key: string]: unknown;
}

export interface Decision {
  readonly id: string;
  readonly replay_hash: string;
  readonly verdict: Verdict;
  readonly decided_by: string;
  readonly reason: string;
  readonly overrode_recommendation: boolean;
  readonly without_baseline: boolean;
  readonly decided_at: string;
  readonly [key: string]: unknown;
}

/**
 * Everything one screen needs about one replay, resolved in a single
 * call.
 *
 * The alternative — the browser fanning out to status/quality/manifest/
 * decision — is four round-trips through two hops for one screen, and
 * three of the four legitimately 404 while a replay is still running.
 * Composing here means the screen gets one answer that is internally
 * consistent, and `null` genuinely means "not available yet".
 */
export interface ReplayReview {
  readonly execution: Record<string, unknown>;
  readonly quality: QualityEvaluation | null;
  readonly manifest: Record<string, unknown> | null;
  readonly decision: Decision | null;
  /** Precomputed so every consumer applies the same gate rules. */
  readonly gate: GateSummary;
}

/**
 * The gate's own reading of the evaluation, computed once here rather
 * than re-derived in the UI.
 *
 * `requiresOverride` / `requiresBaselineAck` mirror the rules Atlas
 * enforces in `approval.py::check`. Duplicating them is deliberate:
 * this copy drives what the FORM asks for, so the operator is told
 * up-front what will be required. Atlas remains the enforcer — a
 * mismatch here can only produce a refused submit, never a decision
 * Atlas would have blocked.
 */
export interface GateSummary {
  readonly evaluated: boolean;
  readonly hasBaseline: boolean;
  readonly qualityRegression: boolean;
  readonly blocking: PromotionRecommendation[];
  readonly verdictCounts: Record<string, number>;
  readonly requiresOverride: boolean;
  readonly requiresBaselineAck: boolean;
}

export function summarizeGate(
  quality: QualityEvaluation | null,
): GateSummary {
  if (quality === null) {
    return {
      evaluated: false,
      hasBaseline: false,
      qualityRegression: false,
      blocking: [],
      verdictCounts: {},
      requiresOverride: false,
      requiresBaselineAck: false,
    };
  }
  const promotions = quality.promotions ?? [];
  const verdictCounts: Record<string, number> = {};
  for (const promo of promotions) {
    verdictCounts[promo.verdict] = (verdictCounts[promo.verdict] ?? 0) + 1;
  }
  const blocking = promotions.filter((p) => p.verdict === 'Rejected');
  const hasBaseline = quality.regression !== null && quality.regression !== undefined;
  const qualityRegression = quality.regression?.quality_regression ?? false;
  return {
    evaluated: true,
    hasBaseline,
    qualityRegression,
    blocking,
    verdictCounts,
    requiresOverride: blocking.length > 0 || qualityRegression,
    requiresBaselineAck: !hasBaseline,
  };
}
