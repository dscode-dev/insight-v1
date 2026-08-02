// Consolidation Sprint 0 Task 7 — legacy dependency boundary.
//
// Playmaker, Pundit, Atrium and Plaza are retired/detached. The
// console must not import from them or call their service endpoints.
// Scans every source file for legacy module imports / service hosts
// and exits non-zero on a hit. Wired into `npm run check:boundaries`
// (runs in CI next to lint + typecheck).
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const LEGACY = ["playmaker", "pundit", "atrium", "plaza", "insight-magnus"];
const EXTS = new Set([".ts", ".tsx", ".js", ".jsx", ".mjs"]);
const SKIP_DIRS = new Set(["node_modules", ".next", ".git", "scripts"]);

// Only flag actionable dependencies: import/require statements and
// service URLs — not prose in comments.
const PATTERNS = LEGACY.flatMap((name) => [
  new RegExp(String.raw`from\s+["'][^"']*${name}[^"']*["']`, "i"),
  new RegExp(String.raw`require\(["'][^"']*${name}[^"']*["']\)`, "i"),
  new RegExp(String.raw`https?://[^"'\s]*${name}[^"'\s]*`, "i"),
]);

function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    if (SKIP_DIRS.has(entry)) continue;
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) yield* walk(p);
    else if (EXTS.has(p.slice(p.lastIndexOf(".")))) yield p;
  }
}

const violations = [];
for (const file of walk(process.cwd())) {
  const body = readFileSync(file, "utf8");
  for (const pattern of PATTERNS) {
    const hit = body.match(pattern);
    if (hit) violations.push(`${file}: ${hit[0]}`);
  }
}

if (violations.length > 0) {
  console.error("Legacy service dependencies found:");
  for (const v of violations) console.error("  " + v);
  process.exit(1);
}
console.log("boundaries OK — no legacy service dependencies");
