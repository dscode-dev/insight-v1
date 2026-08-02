// CONSOLE-IDENTITY-A — Operational Identity + Delegation adapter. SERVER-ONLY.
//
// Typed adapter over the Gateway (the AUTHORITY on operational identity + grants).
// The Console never resolves delegation locally and never trusts the browser: it
// forwards the verified operator session token; the Gateway derives identity from
// its own grant store. Reuses the delegation.ts SHAPE + guards — no parallel model.

import { adminFetch, ConsoleApiError } from "@/lib/admin-api";
import {
  assertOperatorPreserved,
  type DelegationContext,
  type DelegationMode,
  type DelegationSubjectType,
} from "@/lib/control-plane/security/delegation";

const BASE = "/v1/console/identity";

/** Server-resolved authoring identity for the current operator. */
export interface ResolvedIdentity {
  /** Always present — the real operator is never dropped. `operator:<id>`. */
  readonly executedBy: string;
  readonly operatorId: string;
  /** Effective operational identity id (== operatorId when acting as self). */
  readonly identityId: string;
  readonly identityKind: "operator" | "official_identity" | "agent";
  readonly publicActor: string | null;
  readonly delegation: DelegationContext | null;
}

interface RawResolve {
  executed_by?: string;
  operator_id?: string;
  identity_id?: string;
  identity_kind?: string;
  public_actor?: string | null;
  delegation?: { delegation_id?: string; subject_id?: string; subject_type?: string } | null;
}

function toDelegationContext(operatorId: string, raw: RawResolve["delegation"]): DelegationContext | null {
  if (!raw || !raw.delegation_id) return null;
  const ctx: DelegationContext = {
    delegationId: raw.delegation_id,
    operatorId, // the REAL operator — preserved by construction
    subjectType: (raw.subject_type as DelegationSubjectType) ?? "official_identity",
    subjectId: raw.subject_id ?? "",
    mode: "act_as_identity" as DelegationMode, // resolve view does not carry mode; grant list does
    scope: [],
    reason: "",
    issuedAt: "",
    expiresAt: null,
    revokedAt: null,
  };
  // Preservation invariant: the delegation must carry the authenticated operator.
  assertOperatorPreserved(ctx, operatorId);
  return ctx;
}

/**
 * Resolve the effective authoring identity for the verified operator. `delegationId`
 * is an OPTIONAL server-side reference (never browser-supplied); omit it for the
 * default self identity (identity == operator).
 */
export async function resolveOperationalIdentity(
  operatorToken: string | null,
  correlationId: string | null,
  delegationId?: string | null,
): Promise<ResolvedIdentity> {
  const qs = delegationId ? `?delegation_id=${encodeURIComponent(delegationId)}` : "";
  const res = await adminFetch(`${BASE}/resolve${qs}`, {
    operatorToken: operatorToken ?? undefined,
    correlationId: correlationId ?? undefined,
  });
  if (!res.ok) throw new ConsoleApiError(res.status, "identity_resolve_failed");
  const raw = (await res.json()) as RawResolve;
  const operatorId = raw.operator_id ?? "";
  return {
    executedBy: raw.executed_by ?? `operator:${operatorId}`,
    operatorId,
    identityId: raw.identity_id || operatorId, // NULL/absent → operator (compat)
    identityKind: (raw.identity_kind as ResolvedIdentity["identityKind"]) ?? "operator",
    publicActor: raw.public_actor ?? null,
    delegation: toDelegationContext(operatorId, raw.delegation ?? null),
  };
}

export interface GrantInput {
  readonly subjectType: DelegationSubjectType;
  readonly subjectId: string;
  readonly mode: DelegationMode;
  readonly scope?: string[];
  readonly reason: string;
  readonly publicActor?: string;
  readonly expiresAt?: string; // RFC3339
}

export interface GrantResult {
  readonly delegationId: string;
  readonly operatorId: string;
  readonly subjectType: string;
  readonly subjectId: string;
  readonly mode: string;
  readonly issuedAt: string;
}

/** Create an explicit, revocable grant for the verified operator. */
export async function grantDelegation(
  operatorToken: string | null,
  correlationId: string | null,
  input: GrantInput,
): Promise<GrantResult> {
  const res = await adminFetch(`${BASE}/delegations`, {
    method: "POST",
    operatorToken: operatorToken ?? undefined,
    correlationId: correlationId ?? undefined,
    body: {
      subject_type: input.subjectType,
      subject_id: input.subjectId,
      mode: input.mode,
      scope: input.scope ?? [],
      reason: input.reason,
      public_actor: input.publicActor ?? "",
      expires_at: input.expiresAt ?? "",
    },
  });
  if (!res.ok) throw new ConsoleApiError(res.status, "delegation_grant_failed");
  const r = (await res.json()) as Record<string, string>;
  return {
    delegationId: r.delegation_id ?? "",
    operatorId: r.operator_id ?? "",
    subjectType: r.subject_type ?? "",
    subjectId: r.subject_id ?? "",
    mode: r.mode ?? "",
    issuedAt: r.issued_at ?? "",
  };
}

/** Revoke one of the operator's own grants (idempotent). */
export async function revokeDelegation(
  operatorToken: string | null,
  correlationId: string | null,
  delegationId: string,
): Promise<boolean> {
  const res = await adminFetch(`${BASE}/delegations/${encodeURIComponent(delegationId)}`, {
    method: "DELETE",
    operatorToken: operatorToken ?? undefined,
    correlationId: correlationId ?? undefined,
  });
  if (!res.ok) throw new ConsoleApiError(res.status, "delegation_revoke_failed");
  const r = (await res.json()) as { revoked?: boolean };
  return r.revoked === true;
}

export interface DelegationSummary {
  readonly delegationId: string;
  readonly subjectType: string;
  readonly subjectId: string;
  readonly mode: string;
  readonly reason: string;
  readonly publicActor: string | null;
  readonly active: boolean;
  readonly issuedAt: string;
  readonly expiresAt: string | null;
  readonly revokedAt: string | null;
}

/** List the verified operator's grants (never another operator's). */
export async function listDelegations(
  operatorToken: string | null,
  correlationId: string | null,
): Promise<DelegationSummary[]> {
  const res = await adminFetch(`${BASE}/delegations`, {
    operatorToken: operatorToken ?? undefined,
    correlationId: correlationId ?? undefined,
  });
  if (!res.ok) throw new ConsoleApiError(res.status, "delegation_list_failed");
  const r = (await res.json()) as { items?: Record<string, unknown>[] };
  return (r.items ?? []).map((it) => ({
    delegationId: String(it.delegation_id ?? ""),
    subjectType: String(it.subject_type ?? ""),
    subjectId: String(it.subject_id ?? ""),
    mode: String(it.mode ?? ""),
    reason: String(it.reason ?? ""),
    publicActor: (it.public_actor as string | null) ?? null,
    active: it.active === true,
    issuedAt: String(it.issued_at ?? ""),
    expiresAt: (it.expires_at as string | null) ?? null,
    revokedAt: (it.revoked_at as string | null) ?? null,
  }));
}
