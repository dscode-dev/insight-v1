// The console must reach every platform service THROUGH the Control Plane.
//
//   insight-context.md v2.0 — Insight Console
//   O Console nunca acessa diretamente os demais serviços.
//   Toda comunicação ocorre através do Insight Control Plane.
//
// Fase B moved twelve direct adapters. `lib/robozao.ts` was the thirteenth and
// survived because it looked harmless: it forwarded the operator's own session
// rather than a service credential, so the usual check — "does the console
// hold a token for that service?" — said no.
//
// It held the address instead:
//
//   process.env.ROBOZAO_GATEWAY_URL ?? "http://robozao-gateway:8095"
//
// A compiled-in default is a route. Removing the variable from the deployment
// changed nothing, and the container's clean environment made the console look
// isolated when it was not.
//
// So this test looks for ADDRESSES, not credentials.

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = join(__dirname, "..");
const SCAN_DIRS = ["lib", "app", "components"];
const SKIP = new Set(["node_modules", ".next", "tests"]);

/** Service hostnames that only the Control Plane may address. */
const SERVICE_HOSTS = [
  "robozao-gateway",
  "insight-robozao-gateway",
  "insight-explorer",
  "insight-atlas",
  "insight-anvil",
  "insight-nexus",
  "insight-sport-hub",
  "insight-social",
];

/** Environment variables naming a service address or credential. */
const SERVICE_ENV = [
  "ROBOZAO_GATEWAY_URL",
  "ADMIN_API_BASE_URL",
  "EXPLORER_API_BASE_URL",
  "EXPLORER_OPS_TOKEN",
  "ATLAS_API_BASE_URL",
  "ATLAS_INTERNAL_TOKEN",
  "NEXUS_API_BASE_URL",
  "ANVIL_API_BASE_URL",
  "ADMIN_API_INTERNAL_TOKEN",
];

function* walk(dir: string): Generator<string> {
  for (const entry of readdirSync(dir)) {
    if (SKIP.has(entry)) continue;
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      yield* walk(path);
    } else if (/\.(ts|tsx)$/.test(path)) {
      yield path;
    }
  }
}

/**
 * Strip comments before matching.
 *
 * The module that used to hold the address now explains that it did, and a
 * checker that fails on its own explanation gets deleted rather than obeyed.
 * Same rule as scripts/check-boundaries.mjs.
 */
function codeOnly(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

describe("the console holds no route to a platform service", () => {
  const files = SCAN_DIRS.flatMap((dir) => [...walk(join(ROOT, dir))]);

  it("scans a non-trivial number of files", () => {
    // Guards against a broken walk silently passing everything.
    expect(files.length).toBeGreaterThan(50);
  });

  // Matched only inside a URL.
  //
  // These names are also legitimate SERVICE IDENTIFIERS — the registry keys a
  // service as "robozao-gateway", a display name says "Robozão Gateway", a
  // dependency list names "insight-social". Those are data about the platform,
  // not routes into it. A checker that cannot tell an id from an address
  // reports ten findings, nine of them noise, and stops being read.
  it("addresses no service host", () => {
    const violations: string[] = [];
    for (const file of files) {
      const code = codeOnly(readFileSync(file, "utf8"));
      for (const host of SERVICE_HOSTS) {
        const asUrl = new RegExp(`(https?:)?//${host}[:/"'\`]`);
        if (asUrl.test(code)) {
          violations.push(`${file.slice(ROOT.length + 1)}: //${host}`);
        }
      }
    }
    expect(violations).toEqual([]);
  });

  /**
   * What is left, named rather than tolerated.
   *
   * `lib/control-plane/config.ts` still declares the cloud Gateway's address
   * and token, and `adapters/gateway.ts` still fetches with them. It is
   * UNREACHABLE — `PlatformSnapshotService` is its only caller and no route or
   * component imports that — and dormant in the deployment, because the
   * variables are unset so the adapter reports "not configured" instead of
   * calling. But dormant is not absent, and the next screen that imports the
   * barrel would wake it up.
   *
   * Removing it means deleting the snapshot/registry subsystem, which is a
   * change of its own. Asserting the exact set here does two things: it stops
   * anything NEW from being added, and it keeps the remainder written down
   * where the next person looks — the same reason REMOVED_FROM_NAV exists in
   * nav-config.tsx.
   */
  const KNOWN_REMAINING = [
    "lib/control-plane/config.ts: ADMIN_API_BASE_URL",
    "lib/control-plane/config.ts: ADMIN_API_INTERNAL_TOKEN",
    "lib/control-plane/config.ts: EXPLORER_API_BASE_URL",
    "lib/control-plane/config.ts: ROBOZAO_GATEWAY_URL",
  ];

  it("reads no service address or credential outside the known remainder", () => {
    const violations: string[] = [];
    for (const file of files) {
      const code = codeOnly(readFileSync(file, "utf8"));
      for (const name of SERVICE_ENV) {
        if (code.includes(name)) {
          violations.push(`${file.slice(ROOT.length + 1)}: ${name}`);
        }
      }
    }
    expect(violations.sort()).toEqual(KNOWN_REMAINING);
  });

  // The seven routes that used to call the Node Agent directly now go through
  // the Control Plane. This is the half of Fase C that was live.
  it("reaches the Node Agent only through the Control Plane", () => {
    const source = readFileSync(join(ROOT, "lib", "robozao.ts"), "utf8");
    const code = codeOnly(source);
    expect(code).not.toMatch(/robozao-gateway:8095/);
    expect(code).not.toMatch(/process\.env\.ROBOZAO_GATEWAY_URL/);
    expect(code).toContain("controlPlaneFetch");
    expect(code).toContain("/node-agent");
  });

  // A catch-all for the shape, so a service variable nobody thought to add to
  // SERVICE_ENV is still caught. Anything new here is a decision, not an
  // oversight — which is the point of asserting the whole set.
  it("reads only the two URL/token variables it is allowed", () => {
    const found = new Set<string>();
    for (const file of files) {
      const code = codeOnly(readFileSync(file, "utf8"));
      for (const match of code.matchAll(/process\.env\.([A-Z0-9_]+)/g)) {
        const name = match[1];
        if (name && /_URL$|_TOKEN$/.test(name)) {
          found.add(name);
        }
      }
    }
    expect([...found].sort()).toEqual([
      // The Control Plane. The console's one upstream.
      "CONSOLE_API_BASE_URL",
      // The console's OWN audit store, not another service's. Optional and
      // unset in the deployment (the durable audit spine lives in the Control
      // Plane); this is the vestigial local path, kept so an audit write has
      // somewhere to go if it is ever configured.
      "CONSOLE_AUDIT_DATABASE_URL",
    ]);
  });
});
