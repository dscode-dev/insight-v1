// Which reminder writes are governed mutations. SERVER-ONLY.
//
// Extracted from the route handler for the same reason
// `quality-gate-routing.ts` was: this one classification decides whether
// a request takes the governed path (capability → authorize → audit
// intent → mutate → audit outcome) or the ordinary one, and getting it
// wrong is silent — the request still succeeds, just with no trail.
//
// Only MUTE is governed. Marking a rotation done, reporting an observed
// expiry and creating a policy all leave their evidence in the row
// itself. A mute leaves nothing once it lapses, and what it changes is
// who finds out that a credential is about to expire.
//
// FAILS CLOSED. A path that ends in `/mute` but does not parse is
// REFUSED rather than demoted to the ordinary branch — demoting it would
// forward the mute upstream unaudited, which is the exact outcome this
// exists to prevent.

export type ReminderRoute =
  | { kind: "governed"; slug: string }
  | { kind: "ordinary" }
  | { kind: "refuse"; reason: string };

const MUTE_SUFFIX = "/mute";
const MUTE_PATH = /^([^/]+)\/mute$/;
const SLUG = /^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/;

export function classifyReminderWrite(path: string): ReminderRoute {
  if (!path.endsWith(MUTE_SUFFIX)) {
    return { kind: "ordinary" };
  }

  const match = MUTE_PATH.exec(path);
  if (!match) {
    return { kind: "refuse", reason: "malformed_mute_path" };
  }

  let slug: string;
  try {
    slug = decodeURIComponent(match[1]!);
  } catch {
    // A malformed percent-escape throws. Treating it as ordinary would
    // forward an unaudited mute.
    return { kind: "refuse", reason: "malformed_mute_path" };
  }

  // The same shape the Control Plane enforces on creation. A slug that
  // decoded into a separator could reshape the upstream path AFTER this
  // check has already passed.
  if (!SLUG.test(slug)) {
    return { kind: "refuse", reason: "malformed_mute_path" };
  }

  return { kind: "governed", slug };
}
