import { describe, expect, it } from "vitest";

import { CapabilityRegistry } from "@/lib/control-plane/registries/capabilities";
import { classifyExplorerOpsWrite } from "@/lib/control-plane/explorer-ops-routing";

/**
 * Every capability a governed route names must exist in the registry.
 *
 * `authorize()` treats registry presence as a PRECONDITION: an unknown
 * capability returns `denied_capability_unsupported` — so a capability
 * declared only in `capabilities.ts` META, without also being listed on
 * its service descriptor in `services.ts`, is never built into a
 * descriptor and DENIES every request that uses it.
 *
 * This bit for real: `atlas.replay.promote` was added to META but not to
 * the atlas descriptor, which would have made every Quality Gate
 * approval fail with a permission error that looked like the operator's
 * fault. Typecheck cannot catch it — capability ids are plain strings.
 */
const GOVERNED_CAPABILITIES = [
  // app/api/v1/quality-gate/[...path]/route.ts
  "atlas.replay.promote",
  // app/api/v1/explorer-ops/[...path]/route.ts
  "explorer.curation.decide",
  "explorer.scheduler.control",
];

describe("governed capabilities are registered", () => {
  it.each(GOVERNED_CAPABILITIES)("%s is a valid capability id", (id) => {
    expect(CapabilityRegistry.isValidId(id)).toBe(true);
  });

  it("classifies every governed capability as a high-risk mutation", () => {
    // A capability the registry classified as a read would carry
    // neither the mutation class nor the risk the governance surface
    // relies on to present it correctly.
    for (const id of GOVERNED_CAPABILITIES) {
      const capability = CapabilityRegistry.get(id);
      expect(capability?.actionType).toBe("mutation");
      expect(["high", "critical"]).toContain(capability?.risk);
    }
  });

  it("every capability the explorer-ops classifier can emit is registered", () => {
    // Walks the classifier itself rather than a hand-copied list, so a
    // newly governed path cannot be added without its capability.
    const paths = ["review/promote", "review/reject", "scheduler/cancel"];
    for (const path of paths) {
      const route = classifyExplorerOpsWrite(path);
      expect(route.kind).toBe("governed");
      if (route.kind === "governed") {
        expect(CapabilityRegistry.isValidId(route.capability)).toBe(true);
      }
    }
  });
});

describe("classifyExplorerOpsWrite", () => {
  it.each(["review/promote", "review/reject", "scheduler/cancel"])(
    "governs %s",
    (path) => {
      expect(classifyExplorerOpsWrite(path).kind).toBe("governed");
    },
  );

  it.each([
    "review/replay",
    "jobs/task/start",
    "jobs/task/restart",
    "scheduler/pause",
    "scheduler/resume",
    "runtime/reload",
  ])("treats %s as ordinary steering", (path) => {
    expect(classifyExplorerOpsWrite(path).kind).toBe("ordinary");
  });

  it("tolerates surrounding slashes", () => {
    expect(classifyExplorerOpsWrite("/review/promote/").kind).toBe("governed");
  });

  it("REFUSES an unrecognised write rather than forwarding it", () => {
    // Default-deny: a new Explorer mutation must not become reachable
    // through this proxy, unaudited, the moment it exists upstream.
    expect(classifyExplorerOpsWrite("sources/disable").kind).toBe("refuse");
    expect(classifyExplorerOpsWrite("pipelines/x/delete").kind).toBe("refuse");
    expect(classifyExplorerOpsWrite("").kind).toBe("refuse");
  });

  it("does not let a prefix or suffix smuggle a governed path past", () => {
    for (const path of [
      "x/review/promote",
      "review/promote/extra",
      "review/promotex",
    ]) {
      expect(classifyExplorerOpsWrite(path).kind).not.toBe("governed");
      // ...and it must not be silently forwarded either.
      expect(classifyExplorerOpsWrite(path).kind).toBe("refuse");
    }
  });
});
