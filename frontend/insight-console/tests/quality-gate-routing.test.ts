import { describe, expect, it } from "vitest";

import { classifyQualityGateWrite } from "@/lib/control-plane/quality-gate-routing";

/**
 * This classification is the only thing separating an audited promotion
 * decision from an unaudited one. A promotion decision that reaches
 * Atlas through the ungoverned branch is recorded upstream with no
 * console-side capability check and no audit trail — and the request
 * still succeeds, so nothing surfaces the omission.
 *
 * ATLAS_V1_FROZEN.md makes human approval mandatory before promotion
 * against the frozen baseline; the audit record IS the evidence that
 * requirement was met.
 */
describe("classifyQualityGateWrite", () => {
  it("governs a decision write and extracts the execution id", () => {
    const route = classifyQualityGateWrite("replays/exec-123/decision");
    expect(route).toEqual({ kind: "governed", executionId: "exec-123" });
  });

  it("treats replay submission as an ordinary write", () => {
    // Running a replay changes no baseline — it is not a governance act.
    expect(classifyQualityGateWrite("replays")).toEqual({ kind: "ordinary" });
  });

  it.each([
    "replays/exec-1",
    "decisions",
    "replays/exec-1/quality",
  ])("treats %s as ordinary", (path) => {
    expect(classifyQualityGateWrite(path).kind).toBe("ordinary");
  });

  it.each([
    // Extra segments — must not be demoted to ordinary, because the
    // request would still reach a /decision endpoint upstream.
    "replays/a/b/decision",
    "replays//decision",
    "x/replays/exec-1/decision",
    // Percent-encoded separator: `pathOf` decodes before this runs, but
    // the classification must hold even if that ever changes.
    "replays/a%2Fb/decision",
    "replays/%20/decision",
  ])("REFUSES %s rather than falling through ungoverned", (path) => {
    const route = classifyQualityGateWrite(path);
    // The critical assertion: never "ordinary".
    expect(route.kind).not.toBe("ordinary");
  });

  it("refuses a malformed percent-escape instead of throwing", () => {
    // decodeURIComponent throws on a lone `%`; an uncaught throw here
    // would surface as a 500 rather than a clean refusal.
    const route = classifyQualityGateWrite("replays/%E0%A4%A/decision");
    expect(route.kind).toBe("refuse");
  });

  it("never returns ordinary for anything ending in /decision", () => {
    // The invariant, stated directly: if it reaches a decision
    // endpoint, it is either governed or refused.
    const paths = [
      "replays/exec-1/decision",
      "replays/a/b/decision",
      "replays//decision",
      "nonsense/decision",
      "/decision",
    ];
    for (const path of paths) {
      expect(classifyQualityGateWrite(path).kind).not.toBe("ordinary");
    }
  });
});
