// CONSOLE-IDENTITY-A — Provenance chain (presentational).
// Renders Operator → Operational Identity → Delegation → Public Actor → Provenance.
// The operator (executed_by) is ALWAYS shown, even under delegation. No data
// fetching here; callers pass already-resolved, server-owned values.

export interface ProvenanceData {
  executedBy: string; // operator:<id> — the real operator, never dropped
  operatorId: string;
  identityId: string;
  identityKind: "operator" | "official_identity" | "agent" | string;
  publicActor: string | null;
  delegation: { delegationId: string; subjectType: string; subjectId: string } | null;
}

function Node({ label, value, muted }: { label: string; value: string; muted?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className={muted ? "text-sm text-muted-foreground" : "text-sm font-medium"}>{value}</span>
    </div>
  );
}

export function ProvenanceChain({ data }: { data: ProvenanceData }) {
  const delegated = data.delegation !== null;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border border-border bg-card p-3">
      <Node label="Operator (executed_by)" value={data.operatorId} />
      <span className="text-muted-foreground">→</span>
      <Node
        label="Operational Identity"
        value={`${data.identityId}${data.identityKind !== "operator" ? ` · ${data.identityKind}` : ""}`}
        muted={!delegated}
      />
      <span className="text-muted-foreground">→</span>
      <Node
        label="Delegation"
        value={delegated ? `${data.delegation!.subjectType}:${data.delegation!.subjectId}` : "none (self)"}
        muted={!delegated}
      />
      <span className="text-muted-foreground">→</span>
      <Node label="Public Actor" value={data.publicActor ?? "—"} muted={data.publicActor === null} />
    </div>
  );
}
