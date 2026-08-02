// Gateway Trust & Safety adapter (CONSOLE-SOCIAL-A2). SERVER-ONLY.
//
// Reports + moderation history are GATEWAY-owned (moderation_reports /
// moderation_actions). This reuses the existing operator/service-token moderation
// reads (lib/moderation) — no report/moderation persistence is duplicated in
// Social or Console. Read-only. Cross-domain target correlation is server-side.

import { fetchReports, fetchActions } from "@/lib/moderation";

export interface TargetRef {
  readonly targetType: string; // post | comment | user | agent | community
  readonly targetId: string;
}

export const GatewayTrustSafety = {
  async reports(query = "limit=100") {
    return fetchReports(query);
  },
  async actions(limit = 100) {
    return fetchActions(limit);
  },
  /** Reports + moderation actions correlated to a specific Social entity (server-side). */
  async forTarget(target: TargetRef) {
    const [reportsPage, actionsPage] = await Promise.all([
      fetchReports("limit=200"),
      fetchActions(200),
    ]);
    const reports = reportsPage.reports.filter(
      (r) => r.target_type === target.targetType && r.target_id === target.targetId,
    );
    const actions = (actionsPage.actions as Array<{ target_type: string; target_id: string }>).filter(
      (a) => a.target_type === target.targetType && a.target_id === target.targetId,
    );
    return { reports, actions };
  },
};
