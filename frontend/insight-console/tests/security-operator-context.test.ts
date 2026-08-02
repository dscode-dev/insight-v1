// CONSOLE-SECURITY-A0 — operator context + attribution tests.

import { describe, expect, it } from "vitest";

import { buildOperatorContext, assertNoClientActor } from "@/lib/control-plane/security/operator-context";
import type { ConsoleOperator } from "@/types/auth";

const TOKEN = "session-token-abc";

const OPERATOR: ConsoleOperator = {
  id: "op-uuid-1",
  displayName: "Darlan",
  username: "darlan",
  role: "Operations",
  permissions: ["feed.hide", "audit.read"],
  issuedAt: 0,
  expiresAt: 0,
};

function reqWith(headers: Record<string, string> = {}): Request {
  return new Request("http://console.local/api/v1/moderation/actions", { headers });
}

describe("OperatorContext", () => {
  it("is built only from a server-verified operator, with honest absent fields", () => {
    const ctx = buildOperatorContext(OPERATOR, TOKEN, reqWith({ "x-request-id": "req-1" }));
    expect(ctx.operatorId).toBe("op-uuid-1");
    expect(ctx.operatorUsername).toBe("darlan");
    expect(ctx.identityId).toBe("op-uuid-1"); // operator == identity today
    expect(ctx.authStrength).toBeNull(); // not fabricated
    expect(ctx.authenticatedAt).toBeNull(); // not fabricated
    expect(ctx.delegation).toBeNull(); // no active delegation
    expect(ctx.source).toBe("insight-console");
  });

  it("keeps requestId, correlationId and sessionId DISTINCT concepts", () => {
    const ctx = buildOperatorContext(
      OPERATOR,
      TOKEN,
      reqWith({ "x-request-id": "req-1", "x-correlation-id": "corr-9" }),
    );
    expect(ctx.requestId).toBe("req-1");
    expect(ctx.correlationId).toBe("corr-9"); // distinct chain id
    // sessionId is a real key (sha256 of the token), never the request/correlation id
    expect(ctx.sessionId).not.toBe(ctx.requestId);
    expect(ctx.sessionId).not.toBe(ctx.correlationId);
    expect(ctx.sessionId).toMatch(/^[0-9a-f]{64}$/); // sha256 hex
  });

  it("correlationId defaults to requestId at the chain root (still distinct field)", () => {
    const ctx = buildOperatorContext(OPERATOR, TOKEN, reqWith({ "x-request-id": "req-root" }));
    expect(ctx.requestId).toBe("req-root");
    expect(ctx.correlationId).toBe("req-root");
  });
});

describe("assertNoClientActor", () => {
  it("strips every client-supplied actor field (never authoritative)", () => {
    const body: Record<string, unknown> = {
      action: "remove_content",
      moderator_id: "attacker",
      operator_id: "attacker",
      actor_id: "attacker",
      act_as_user_id: "victim",
      target_id: "post-1",
    };
    assertNoClientActor(body);
    expect(body.moderator_id).toBeUndefined();
    expect(body.operator_id).toBeUndefined();
    expect(body.actor_id).toBeUndefined();
    expect(body.act_as_user_id).toBeUndefined();
    // non-actor fields survive
    expect(body.action).toBe("remove_content");
    expect(body.target_id).toBe("post-1");
  });
});
