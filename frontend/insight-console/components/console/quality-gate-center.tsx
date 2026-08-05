"use client";

// Atlas Quality Gate — the screen where a human approves or rejects a
// replay before its changes are promoted against the frozen baseline.
//
// ATLAS_V1_FROZEN.md: "Every new detector/heuristic MUST pass the
// Quality Gate (regression + promotion) against the frozen baseline
// before promotion. Human approval remains mandatory." Atlas had the
// whole evaluation machinery and no way for a person to record a
// decision on it. This is that missing half.
//
// Design rule followed throughout: never present a gate result as
// cleaner than it is. A replay with no baseline says so; an approval
// that goes against the recommendation makes the operator type why.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  Loader2,
  Play,
  ShieldCheck,
  XCircle,
} from "lucide-react";

import { withBasePath } from "@/lib/base-path";
import { Card, Empty, ErrorBanner, PageHeader, Pill, ts, type Row } from "@/components/console/ops-shared";

const API = "/api/v1/quality-gate";

type Verdict = "approved" | "rejected";

interface GateSummary {
  evaluated: boolean;
  hasBaseline: boolean;
  qualityRegression: boolean;
  blocking: Array<{ agent: string; trend_type: string; reasons: string[] }>;
  verdictCounts: Record<string, number>;
  requiresOverride: boolean;
  requiresBaselineAck: boolean;
}

interface Review {
  execution: Row;
  quality: Row | null;
  manifest: Row | null;
  decision: Row | null;
  gate: GateSummary;
}

async function request(path: string, method = "GET", body?: unknown) {
  const response = await fetch(withBasePath(`${API}/${path}`), {
    method,
    cache: "no-store",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    // The gate's refusal code (override_required / baseline_required /
    // decision_exists) is the only thing telling the operator what is
    // missing, so it is preserved rather than flattened to "failed".
    const error = new Error(
      String(payload.message ?? payload.detail ?? payload.error ?? `HTTP ${response.status}`),
    ) as Error & { code?: string };
    error.code = typeof payload.code === "string" ? payload.code : undefined;
    throw error;
  }
  return payload;
}

export function QualityGateCenter() {
  const [replays, setReplays] = useState<Row[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    try {
      const payload = await request("replays");
      setReplays(Array.isArray(payload.executions) ? payload.executions : []);
      setUpdated(new Date());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "unreachable");
    }
  }, []);

  const loadReview = useCallback(async (id: string) => {
    try {
      setReview(await request(`replays/${encodeURIComponent(id)}`));
      setError(null);
    } catch (e) {
      setReview(null);
      setError(e instanceof Error ? e.message : "unreachable");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 7000);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    if (selected) void loadReview(selected);
  }, [selected, loadReview]);

  return (
    <div className="space-y-4">
      <PageHeader
        icon={ShieldCheck}
        title="Quality Gate"
        subtitle="Deterministic replay review and promotion approval — Atlas frozen baseline"
        onRefresh={() => void refresh()}
        updated={updated}
      />

      {error ? <ErrorBanner>{error}</ErrorBanner> : null}

      <SubmitReplay onSubmitted={refresh} onError={setError} />

      <Card title="Replays">
        {replays.length === 0 ? (
          <Empty>No replays recorded. Submit one above to evaluate a candidate build.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-wider text-muted-foreground">
                  <th className="pb-2">Execution</th>
                  <th className="pb-2">Source</th>
                  <th className="pb-2">Status</th>
                  <th className="pb-2">Requester</th>
                  <th className="pb-2">Submitted</th>
                  <th className="pb-2" />
                </tr>
              </thead>
              <tbody>
                {replays.map((row) => {
                  const id = String(row.execution_id ?? "");
                  return (
                    <tr key={id} className="border-t border-border/50">
                      <td className="py-2 font-mono text-xs">{id.slice(0, 12)}</td>
                      <td className="py-2">{String(row.source ?? "—")}</td>
                      <td className="py-2"><Pill value={String(row.status ?? "unknown")} /></td>
                      <td className="py-2">{String(row.requester ?? "—")}</td>
                      <td className="py-2 text-xs text-muted-foreground">{ts(row.submitted_at)}</td>
                      <td className="py-2 text-right">
                        <button
                          onClick={() => setSelected(id)}
                          className="ix-transition rounded-lg border border-border px-2.5 py-1 text-xs hover:bg-accent"
                        >
                          Review
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {selected && review ? (
        <ReviewPanel
          review={review}
          executionId={selected}
          onDecided={() => {
            void loadReview(selected);
            void refresh();
          }}
          onError={setError}
        />
      ) : null}
    </div>
  );
}

function SubmitReplay({
  onSubmitted,
  onError,
}: {
  onSubmitted: () => void;
  onError: (message: string) => void;
}) {
  const [source, setSource] = useState("dataset");
  const [competition, setCompetition] = useState("");
  const [season, setSeason] = useState("");
  const [busy, setBusy] = useState(false);

  const needsCompetition = source !== "dataset" && source !== "match";

  return (
    <Card title="Submit replay">
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs">
          <span className="mb-1 block text-muted-foreground">Source</span>
          <select
            value={source}
            onChange={(e) => setSource(e.target.value)}
            className="rounded-lg border border-border bg-card px-2 py-1.5 text-sm"
          >
            {["dataset", "competition", "season", "mission"].map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>
        {needsCompetition ? (
          <label className="text-xs">
            <span className="mb-1 block text-muted-foreground">Competition</span>
            <input
              value={competition}
              onChange={(e) => setCompetition(e.target.value)}
              className="rounded-lg border border-border bg-card px-2 py-1.5 text-sm"
            />
          </label>
        ) : null}
        {source === "season" ? (
          <label className="text-xs">
            <span className="mb-1 block text-muted-foreground">Season</span>
            <input
              value={season}
              onChange={(e) => setSeason(e.target.value)}
              className="rounded-lg border border-border bg-card px-2 py-1.5 text-sm"
            />
          </label>
        ) : null}
        <button
          disabled={busy || (needsCompetition && !competition)}
          onClick={async () => {
            setBusy(true);
            try {
              await request("replays", "POST", {
                source,
                ...(competition ? { competition } : {}),
                ...(season ? { season } : {}),
              });
              onSubmitted();
            } catch (e) {
              onError(e instanceof Error ? e.message : "submit failed");
            } finally {
              setBusy(false);
            }
          }}
          className="ix-transition inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-40"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
          Run replay
        </button>
      </div>
    </Card>
  );
}

function ReviewPanel({
  review,
  executionId,
  onDecided,
  onError,
}: {
  review: Review;
  executionId: string;
  onDecided: () => void;
  onError: (message: string) => void;
}) {
  const { gate, quality, manifest, decision } = review;
  const diff = (quality?.regression as Row | null)?.diff as Row | undefined;

  return (
    <div className="space-y-4">
      <Card title={`Gate — ${executionId.slice(0, 12)}`}>
        {!gate.evaluated ? (
          <Empty>
            This replay has not produced a quality evaluation yet. Nothing can be
            approved until it does.
          </Empty>
        ) : (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2">
              {Object.entries(gate.verdictCounts).map(([verdict, count]) => (
                <span
                  key={verdict}
                  className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                >
                  {verdict}: {count}
                </span>
              ))}
            </div>

            {!gate.hasBaseline ? (
              <ErrorBanner>
                No frozen baseline was available for this replay, so no regression
                was computed. &ldquo;No regression detected&rdquo; would be
                meaningless here — approving requires acknowledging that
                explicitly.
              </ErrorBanner>
            ) : null}

            {gate.qualityRegression ? (
              <ErrorBanner>
                The regression report flags a quality regression against the
                baseline.
              </ErrorBanner>
            ) : null}

            {gate.blocking.length > 0 ? (
              <div className="space-y-1">
                <p className="text-xs font-medium text-red-400">
                  {gate.blocking.length} detector(s) rejected by the gate
                </p>
                {gate.blocking.map((b) => (
                  <p key={`${b.agent}:${b.trend_type}`} className="text-xs text-muted-foreground">
                    <span className="font-mono">{b.trend_type}</span> ({b.agent}) — {b.reasons.join("; ")}
                  </p>
                ))}
              </div>
            ) : null}
          </div>
        )}
      </Card>

      {diff ? <RegressionDiffView diff={diff} /> : null}

      {manifest ? (
        <Card title="Replay manifest">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-3">
            {Object.entries(manifest)
              .filter(([, v]) => typeof v !== "object")
              .map(([key, value]) => (
                <div key={key}>
                  <dt className="text-muted-foreground">{key}</dt>
                  <dd className="font-mono">{String(value)}</dd>
                </div>
              ))}
          </dl>
        </Card>
      ) : null}

      {decision ? (
        <RecordedDecision decision={decision} />
      ) : gate.evaluated ? (
        <DecisionForm
          gate={gate}
          executionId={executionId}
          onDecided={onDecided}
          onError={onError}
        />
      ) : null}
    </div>
  );
}

function RegressionDiffView({ diff }: { diff: Row }) {
  const rows = useMemo(
    () =>
      [
        ["Lost detections", diff.lost_detections],
        ["New detections", diff.new_detections],
        ["Confidence changes", diff.confidence_changes],
        ["Strength changes", diff.strength_changes],
        ["Trend changes", diff.trend_changes],
      ] as Array<[string, unknown]>,
    [diff],
  );

  return (
    <Card title="Regression diff vs frozen baseline">
      <p className="mb-3 text-xs text-muted-foreground">
        baseline <span className="font-mono">{String(diff.baseline_hash ?? "—").slice(0, 16)}</span>
        {" → candidate "}
        <span className="font-mono">{String(diff.candidate_hash ?? "—").slice(0, 16)}</span>
        {diff.identical === true ? " — identical" : ""}
      </p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map(([label, value]) => {
          const list = Array.isArray(value) ? (value as Row[]) : [];
          return (
            <div key={label} className="rounded-lg border border-border/60 p-3">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</p>
              <p className="mt-1 text-lg font-semibold">{list.length}</p>
              {list.slice(0, 4).map((entry, i) => (
                <p key={i} className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground">
                  {String(entry.trend_type ?? entry.type ?? JSON.stringify(entry))}
                  {entry.from !== undefined && entry.to !== undefined
                    ? ` ${Number(entry.from).toFixed(3)} → ${Number(entry.to).toFixed(3)}`
                    : ""}
                </p>
              ))}
              {list.length > 4 ? (
                <p className="mt-0.5 text-[11px] text-muted-foreground">+{list.length - 4} more</p>
              ) : null}
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function RecordedDecision({ decision }: { decision: Row }) {
  const approved = decision.verdict === "approved";
  return (
    <Card title="Recorded decision">
      <div className="flex items-start gap-3">
        {approved ? (
          <CheckCircle2 className="mt-0.5 h-5 w-5 text-emerald-400" />
        ) : (
          <XCircle className="mt-0.5 h-5 w-5 text-red-400" />
        )}
        <div className="space-y-1 text-sm">
          <p>
            <span className="font-medium">{String(decision.verdict)}</span> by{" "}
            <span className="font-medium">{String(decision.decided_by)}</span>
            <span className="ml-2 text-xs text-muted-foreground">{ts(decision.decided_at)}</span>
          </p>
          <p className="text-muted-foreground">{String(decision.reason)}</p>
          {decision.overrode_recommendation === true ? (
            <p className="flex items-center gap-1.5 text-xs text-amber-400">
              <AlertTriangle className="h-3.5 w-3.5" />
              Approved against the gate&apos;s recommendation
            </p>
          ) : null}
          {decision.without_baseline === true ? (
            <p className="flex items-center gap-1.5 text-xs text-amber-400">
              <AlertTriangle className="h-3.5 w-3.5" />
              Decided with no frozen baseline to diff against
            </p>
          ) : null}
        </div>
      </div>
    </Card>
  );
}

function DecisionForm({
  gate,
  executionId,
  onDecided,
  onError,
}: {
  gate: GateSummary;
  executionId: string;
  onDecided: () => void;
  onError: (message: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [override, setOverride] = useState(false);
  const [ackBaseline, setAckBaseline] = useState(false);
  const [busy, setBusy] = useState(false);

  // Mirrors atlas/backtest/approval.py::check. Atlas remains the
  // enforcer — this only tells the operator up-front what will be
  // required, so an approval isn't refused after the fact.
  const approvalBlocked =
    (gate.requiresOverride && !override) || (gate.requiresBaselineAck && !ackBaseline);

  const submit = async (verdict: Verdict) => {
    setBusy(true);
    try {
      await request(`replays/${encodeURIComponent(executionId)}/decision`, "POST", {
        verdict,
        reason,
        override_recommendation: override,
        acknowledge_no_baseline: ackBaseline,
      });
      setReason("");
      onDecided();
    } catch (e) {
      const err = e as Error & { code?: string };
      onError(err.code ? `${err.code}: ${err.message}` : err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Decision">
      <div className="space-y-3">
        <label className="block text-xs">
          <span className="mb-1 block text-muted-foreground">
            Justification (recorded permanently and required for both verdicts)
          </span>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            className="w-full rounded-lg border border-border bg-card px-2 py-1.5 text-sm"
            placeholder="What you reviewed and why this is the right call"
          />
        </label>

        {gate.requiresOverride ? (
          <label className="flex items-start gap-2 text-xs text-amber-400">
            <input
              type="checkbox"
              checked={override}
              onChange={(e) => setOverride(e.target.checked)}
              className="mt-0.5"
            />
            <span>
              I am approving <strong>against</strong> the Quality Gate&apos;s
              recommendation. This is recorded as an override.
            </span>
          </label>
        ) : null}

        {gate.requiresBaselineAck ? (
          <label className="flex items-start gap-2 text-xs text-amber-400">
            <input
              type="checkbox"
              checked={ackBaseline}
              onChange={(e) => setAckBaseline(e.target.checked)}
              className="mt-0.5"
            />
            <span>
              I acknowledge this replay was <strong>not</strong> diffed against a
              frozen baseline, so its regression profile is unverified.
            </span>
          </label>
        ) : null}

        <div className="flex gap-2">
          <button
            disabled={busy || !reason.trim() || approvalBlocked}
            onClick={() => void submit("approved")}
            className="ix-transition inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-400 hover:bg-emerald-500/20 disabled:opacity-40"
          >
            <ClipboardCheck className="h-3.5 w-3.5" /> Approve promotion
          </button>
          <button
            // Rejecting is never gated on an override or an
            // acknowledgement: refusing to promote is always safe, so it
            // must never be harder than approving.
            disabled={busy || !reason.trim()}
            onClick={() => void submit("rejected")}
            className="ix-transition inline-flex items-center gap-1.5 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-1.5 text-xs font-medium text-red-400 hover:bg-red-500/20 disabled:opacity-40"
          >
            <XCircle className="h-3.5 w-3.5" /> Reject
          </button>
        </div>
      </div>
    </Card>
  );
}
