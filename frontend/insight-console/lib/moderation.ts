// Moderation Center client (Store-A Part 6) — server-side only. Thin wrappers
// over the Gateway's admin moderation API (X-Console-Service-Token, sent by
// adminFetch). The browser only ever talks to the Console BFF.

import { z } from "zod";

import { adminFetch, adminJson, ConsoleApiError } from "@/lib/admin-api";
import type { Permission } from "@/types/auth";

export const reportSchema = z.object({
  id: z.string(),
  reporter_id: z.string(),
  target_type: z.string(),
  target_id: z.string(),
  reason: z.string(),
  description: z.string().optional().default(""),
  status: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Report = z.infer<typeof reportSchema>;

export const reportListSchema = z.object({
  reports: z.array(reportSchema),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
});

const aggregateSchema = z.object({ key: z.string(), count: z.number() });
const reasonCountSchema = z.object({ reason: z.string(), count: z.number() });

export const statsSchema = z.object({
  open: z.number(),
  reviewing: z.number(),
  resolved: z.number(),
  dismissed: z.number(),
  by_reason: z.array(reasonCountSchema).nullable().default([]),
  top_posts: z.array(aggregateSchema).nullable().default([]),
  top_users: z.array(aggregateSchema).nullable().default([]),
  top_reporters: z.array(aggregateSchema).nullable().default([]),
});
export type Stats = z.infer<typeof statsSchema>;

export const actionSchema = z.object({
  id: z.string(),
  report_id: z.string().optional().default(""),
  moderator_id: z.string(),
  action: z.string(),
  target_type: z.string(),
  target_id: z.string(),
  note: z.string().optional().default(""),
  created_at: z.string(),
});
export const actionListSchema = z.object({ actions: z.array(actionSchema) });

export async function fetchReports(query: string) {
  const qs = query ? `?${query}` : "";
  return adminJson(`/v1/admin/moderation/reports${qs}`, reportListSchema);
}

export async function fetchStats() {
  return adminJson(`/v1/admin/moderation/stats`, statsSchema);
}

export async function fetchActions(limit = 50) {
  return adminJson(`/v1/admin/moderation/actions?limit=${limit}`, actionListSchema);
}

export interface ActInput {
  moderator_id: string;
  action: string;
  report_id?: string;
  target_type: string;
  target_id: string;
  note?: string;
  suspend_days?: number;
}

/** Permission required for each moderation action (defence-in-depth: the BFF
 * re-validates before calling the Gateway). */
export const ACTION_PERMISSION: Record<string, Permission> = {
  dismiss: "feed.read",
  remove_content: "feed.hide",
  restore_content: "feed.restore",
  suspend_user: "user.suspend",
  ban_user: "user.ban",
  restore_user: "user.suspend",
};

export async function postAction(input: ActInput): Promise<void> {
  const res = await adminFetch(`/v1/admin/moderation/actions`, {
    method: "POST",
    body: input,
  });
  if (!res.ok && res.status !== 204) {
    let detail = `upstream_${res.status}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new ConsoleApiError(res.status, detail);
  }
}
