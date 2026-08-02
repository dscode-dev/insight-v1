// CONSOLE-IDENTITY-A — identity resolution, delegation, audit provenance, and
// backward compatibility. Pure/unit (no live Gateway); the adapter's HTTP is
// exercised via the projection + context helpers.
import { describe, it, expect } from "vitest";

import {
  withResolvedIdentity,
  assertNoClientActor,
  type OperatorContext,
} from "@/lib/control-plane/security/operator-context";
import {
  assertOperatorPreserved,
  rejectSelfDelegation,
  resolveDelegation,
  type DelegationContext,
} from "@/lib/control-plane/security/delegation";
import { buildAuditEvent } from "@/lib/control-plane/security/audit/model";
import { toIngestBody } from "@/lib/control-plane/security/audit/gateway-sink";

function op(overrides: Partial<OperatorContext> = {}): OperatorContext {
  return {
    operatorId: "op-1", operatorDisplayName: "Op", operatorUsername: "op", identityId: "op-1",
    identityKind: "operator", publicActor: null, sessionId: "s".repeat(64), roles: ["Operations"],
    permissions: [], authStrength: null, delegation: null, correlationId: "c", requestId: "r",
    authenticatedAt: null, source: "insight-console", ...overrides,
  };
}

const grant: DelegationContext = {
  delegationId: "grant-9", operatorId: "op-1", subjectType: "official_identity", subjectId: "ninja",
  mode: "act_as_identity", scope: [], reason: "official post", issuedAt: "", expiresAt: null, revokedAt: null,
};

describe("identity resolution (server-side)", () => {
  it("default context: identity == operator, not delegated (backward compatible)", () => {
    const c = op();
    expect(c.identityId).toBe(c.operatorId);
    expect(c.identityKind).toBe("operator");
    expect(c.delegation).toBeNull();
    expect(c.publicActor).toBeNull();
  });

  it("resolveDelegation() default is null (no ambient delegation)", () => {
    expect(resolveDelegation()).toBeNull();
  });

  it("withResolvedIdentity swaps identity to the delegated subject, operator preserved", () => {
    const c = withResolvedIdentity(op(), {
      identityId: "ninja", identityKind: "official_identity", publicActor: "Ninja", delegation: grant,
    });
    expect(c.operatorId).toBe("op-1");      // operator NEVER dropped
    expect(c.identityId).toBe("ninja");     // identity is now the subject
    expect(c.identityKind).toBe("official_identity");
    expect(c.publicActor).toBe("Ninja");
    expect(c.delegation?.delegationId).toBe("grant-9");
  });

  it("withResolvedIdentity rejects a delegation whose operator != authenticated operator", () => {
    const foreign = { ...grant, operatorId: "someone-else" };
    expect(() => withResolvedIdentity(op(), {
      identityId: "ninja", identityKind: "official_identity", publicActor: null, delegation: foreign,
    })).toThrow(/operator does not match/);
  });
});

describe("delegation invariants", () => {
  it("assertOperatorPreserved passes for matching operator, throws otherwise", () => {
    expect(() => assertOperatorPreserved(grant, "op-1")).not.toThrow();
    expect(() => assertOperatorPreserved(grant, "op-2")).toThrow();
  });
  it("rejectSelfDelegation always throws (no browser self-delegation)", () => {
    expect(() => rejectSelfDelegation("act_as_user_id")).toThrow(/self-delegation is forbidden/);
  });
});

describe("browser can never assert identity/delegation/public_actor", () => {
  it("assertNoClientActor strips identity + delegation + public_actor fields", () => {
    const body: Record<string, unknown> = {
      identity_id: "x", identityId: "x", delegation: {}, delegation_id: "g", public_actor: "Ninja",
      subject_id: "s", operator_id: "forged", reason: "keep me",
    };
    assertNoClientActor(body);
    for (const f of ["identity_id", "identityId", "delegation", "delegation_id", "public_actor", "subject_id", "operator_id"]) {
      expect(f in body).toBe(false);
    }
    expect(body.reason).toBe("keep me"); // non-actor fields survive
  });
});

describe("audit provenance (additive)", () => {
  it("audit event carries operator + identity + publicActor + delegation", () => {
    const c = withResolvedIdentity(op(), {
      identityId: "ninja", identityKind: "official_identity", publicActor: "Ninja", delegation: grant,
    });
    const e = buildAuditEvent({
      operator: c, capability: "social.content.hide", status: "AUTHORIZED",
      authorization: { decision: "allow", reasonCode: "allowed_permission", policySource: "permission:feed.hide" },
    });
    expect(e.actor.operatorId).toBe("op-1");   // executed_by preserved
    expect(e.actor.identityId).toBe("ninja");
    expect(e.actor.publicActor).toBe("Ninja");
    expect(e.delegation.active).toBe(true);
    expect(e.delegation.grantId).toBe("grant-9");
  });

  it("self action: identity == operator, delegation inactive", () => {
    const e = buildAuditEvent({
      operator: op(), capability: "social.user.read", status: "COMPLETED",
      authorization: { decision: "allow", reasonCode: "allowed_superadmin", policySource: "role:SuperAdmin" },
    });
    expect(e.actor.identityId).toBe(e.actor.operatorId);
    expect(e.actor.publicActor).toBeNull();
    expect(e.delegation.active).toBe(false);
  });

  it("ingest body sends only a delegation_id REFERENCE, never identity/subject/public_actor", () => {
    const c = withResolvedIdentity(op(), {
      identityId: "ninja", identityKind: "official_identity", publicActor: "Ninja", delegation: grant,
    });
    const e = buildAuditEvent({
      operator: c, capability: "social.content.hide", status: "COMPLETED",
      authorization: { decision: "allow", reasonCode: "allowed_permission", policySource: "permission:feed.hide" },
    });
    const body = toIngestBody(e, "idem-1");
    expect(body.delegation_id).toBe("grant-9");
    expect(Object.keys(body)).not.toContain("identity_id");
    expect(Object.keys(body)).not.toContain("public_actor");
    expect(Object.keys(body)).not.toContain("operator_id");
  });
});
