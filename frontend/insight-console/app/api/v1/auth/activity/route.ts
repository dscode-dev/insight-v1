// GET /api/v1/auth/activity — live auth_* counters from the Gateway (Auth-A
// Part 11). Read-only + session-gated; the Console observes authentication
// activity but never mutates it.

import { withApiHandler, requirePermission } from "@/lib/api-guard";
import { authActivity } from "@/lib/auth-activity";

export const GET = withApiHandler(async () => {
  await requirePermission("console.access");
  const activity = await authActivity();
  return Response.json(activity, {
    headers: { "cache-control": "no-store" },
  });
});
