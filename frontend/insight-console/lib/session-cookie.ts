// The session cookie name and reader, alone in their own module.
//
// Extracted to break a real import cycle: `session.ts` needs the Control
// Plane adapter to resolve an operator, and the adapter needs the cookie
// to authenticate. Hoisting made it work, which is exactly why it was
// worth removing — a cycle that happens to resolve today is a cycle that
// breaks on an unrelated reorder.

import { cookies } from "next/headers";

export const SESSION_COOKIE = "insight_console_session";

export function readSessionCookie(): string | null {
  return cookies().get(SESSION_COOKIE)?.value ?? null;
}
