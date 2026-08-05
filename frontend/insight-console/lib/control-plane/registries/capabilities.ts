// Capability Registry (CONSOLE-FOUNDATION-A, Stage 3). SERVER-OWNED.
//
// Grammar: `domain.resource.action` (ADR-0002). This is DESCRIPTIVE discovery
// infrastructure, NOT authorization — it never grants a right (SECURITY-A0 owns
// enforcement). Every capability carries real `evidence` (a route/RPC observed
// in CONSOLE-ARCHITECTURE-A). No capability is registered because the roadmap
// wants it later.
//
// State semantics (prompt + ADR-0002):
//  DECLARED     config knows it should exist for this service contract
//  DISCOVERED   runtime confirmed the upstream surface exists
//  AVAILABLE    currently usable
//  DEGRADED     exists but partial failure/dependency reduces quality
//  UNAVAILABLE  exists conceptually but cannot currently be used
//  UNSUPPORTED  the service does not implement it
//
// Foundation policy: READ capabilities are resolved to AVAILABLE/DEGRADED/
// UNAVAILABLE from live service health by the snapshot. MUTATION capabilities
// remain DECLARED — this sprint does not exercise or enable any mutation.

import {
  getServiceSeed,
  listServiceDescriptors,
} from "@/lib/control-plane/registries/services";
import type {
  CapabilityClass,
  CapabilityDescriptor,
  CapabilityPublic,
  CapabilityState,
  HealthState,
  RiskLevel,
} from "@/lib/control-plane/types";

interface CapMeta {
  evidence: string;
  risk?: RiskLevel;
  approvalRequired?: boolean;
}

// Evidence per capability id — each is a route/RPC confirmed by the audit.
const META: Record<string, CapMeta> = {
  "atlas.health.read": { evidence: "GET /health (atlas 1.0.0)" },
  "atlas.intelligence.read": { evidence: "GET /v1/internal/intelligence/* (atlas 1.0.0)" },
  "atlas.replay.read": { evidence: "GET /backtests (atlas 1.0.0)" },
  // The human approval ATLAS_V1_FROZEN.md declares mandatory before any
  // detector/heuristic change is promoted against the frozen baseline.
  // High risk and approval-required for the same reason moderation is:
  // it is an irreversible governance act, and the record of who made it
  // is the only evidence the freeze was respected.
  "atlas.replay.promote": {
    evidence: "POST /backtests/{id}/decision (atlas 1.0.0)",
    risk: "high",
    approvalRequired: true,
  },
  "explorer.health.read": { evidence: "GET /health (explorer)" },
  "explorer.missions.read": { evidence: "GET /explorer/missions (explorer)" },
  "explorer.datasets.read": { evidence: "GET /explorer/datasets (explorer)" },
  "robozao.operations.read": { evidence: "GET /operations/status (robozao-gateway)" },
  "nexus.publications.read": { evidence: "Nexus authed HTTP API (publication ops)" },
  "gateway.platform_health.read": { evidence: "GET /v1/console/platform/health (gateway)" },
  "gateway.audit.read": { evidence: "GET /v1/console/audit (gateway)" },
  "gateway.users.read": { evidence: "GET /v1/console/admin/users (gateway)" },
  "social.moderation.read": { evidence: "GET /v1/admin/moderation/reports (gateway → social)" },
  "social.content.moderate": {
    evidence: "POST /v1/admin/moderation/actions (gateway → social)",
    risk: "high",
    approvalRequired: true,
  },
  "social.agents.read": { evidence: "social AgentService.List/Get via /v1/agents" },
  "social.users.read": { evidence: "social UserService.List (gateway admin)" },
  // CONSOLE-SOCIAL-A1 read plane (gateway → social /console/social/*)
  "social.overview.read": { evidence: "GET /v1/console/social/overview (gateway → social)" },
  "social.activity.read": { evidence: "GET /v1/console/social/activity (gateway → social)" },
  "social.user.read": { evidence: "GET /v1/console/social/users(/:id) (gateway → social)" },
  "social.agent.read": { evidence: "GET /v1/console/social/agents(/:id) (gateway → social)" },
  "social.post.read": { evidence: "GET /v1/console/social/posts(/:id) (gateway → social)" },
  "social.comment.read": { evidence: "GET /v1/console/social/comments(/:id) (gateway → social)" },
  // CONSOLE-SOCIAL-A2 investigation plane
  "social.community.read": { evidence: "GET /v1/console/social/communities(/:id) (gateway → social)" },
  "social.relationship.read": { evidence: "GET /v1/console/social/relationships (gateway → social)" },
  "social.boost.read": { evidence: "GET /v1/console/social/boosts (gateway → social)" },
  "social.save.read": { evidence: "aggregate save_count in posts projections (no saver identities)" },
  "social.investigation.read": { evidence: "composed InvestigationService/TimelineService (server-side)" },
  "trust.report.read": { evidence: "GET /v1/admin/moderation/reports (gateway-owned)" },
  "trust.moderation.read": { evidence: "GET /v1/admin/moderation/actions (gateway-owned)" },
  "audit.event.read": { evidence: "GET /v1/console/audit/events (operator_audit_log)" },
  // CONSOLE-SOCIAL-B enforcement plane (operator-driven mutations; risk/approval
  // derived by classify() = mutation → high + approvalRequired). Each maps to a
  // real Gateway operator command that drives EXISTING enforcement.
  "social.user.suspend": { evidence: "POST /v1/console/social/users/{id}/suspend|unsuspend (moderation_user_state)", risk: "high", approvalRequired: true },
  "social.user.ban": { evidence: "POST /v1/console/social/users/{id}/ban|unban (moderation_user_state + session revoke)", risk: "critical", approvalRequired: true },
  "social.content.hide": { evidence: "POST /v1/console/social/{posts,comments}/{id}/hide (moderation_hidden_content)", risk: "high", approvalRequired: true },
  "social.content.restore": { evidence: "POST /v1/console/social/{posts,comments}/{id}/restore (moderation_hidden_content)", risk: "medium", approvalRequired: true },
  "social.agent.deactivate": { evidence: "POST /v1/console/social/agents/{id}/deactivate (agent_profiles.active)", risk: "high", approvalRequired: true },
  "social.agent.reactivate": { evidence: "POST /v1/console/social/agents/{id}/reactivate (agent_profiles.active)", risk: "medium", approvalRequired: true },
  "trust.report.review": { evidence: "POST /v1/console/social/reports/{id}/review (moderation_reports.status)", risk: "low", approvalRequired: false },
  "trust.report.resolve": { evidence: "POST /v1/console/social/reports/{id}/resolve (moderation_reports.status)", risk: "medium", approvalRequired: true },
  "trust.report.dismiss": { evidence: "POST /v1/console/social/reports/{id}/dismiss (moderation_reports.status)", risk: "medium", approvalRequired: true },
};

const READ_ACTIONS = new Set(["read", "list", "get"]);

function classify(action: string): CapabilityClass {
  return READ_ACTIONS.has(action) ? "read" : "mutation";
}

function parse(id: string): { domain: string; resource: string; action: string } | null {
  const parts = id.split(".");
  if (parts.length !== 3) return null;
  const [domain, resource, action] = parts;
  if (!domain || !resource || !action) return null;
  return { domain, resource, action };
}

function buildDescriptors(): CapabilityDescriptor[] {
  const out: CapabilityDescriptor[] = [];
  for (const svc of listServiceDescriptors()) {
    for (const capId of svc.capabilities) {
      const parsed = parse(capId);
      const meta = META[capId];
      // No evidence ⇒ not a capability. Skip silently (never invent).
      if (!parsed || !meta) continue;
      const actionType = classify(parsed.action);
      const risk: RiskLevel = meta.risk ?? (actionType === "mutation" ? "high" : "low");
      const approvalRequired =
        meta.approvalRequired ?? (actionType === "mutation" && (risk === "high" || risk === "critical"));
      out.push({
        id: capId,
        serviceId: svc.id,
        environmentId: svc.environmentId,
        domain: parsed.domain,
        resource: parsed.resource,
        action: parsed.action,
        actionType,
        risk,
        approvalRequired,
        declaredState: "DECLARED",
        evidence: meta.evidence,
      });
    }
  }
  return out;
}

const DESCRIPTORS = buildDescriptors();
const BY_ID = new Map<string, CapabilityDescriptor>(DESCRIPTORS.map((c) => [c.id, c]));

/**
 * Effective state given the backing service's live health. READ capabilities
 * track health; MUTATION capabilities are never elevated by this foundation.
 */
export function effectiveState(
  cap: CapabilityDescriptor,
  health: HealthState | undefined,
): CapabilityState {
  if (cap.actionType === "mutation") return "DECLARED";
  const seed = getServiceSeed(cap.serviceId);
  // Service not configured for Console access ⇒ cannot be used.
  if (seed && !seed.observable) return "UNAVAILABLE";
  switch (health) {
    case "healthy":
      return "AVAILABLE";
    case "degraded":
      return "DEGRADED";
    case "unavailable":
      return "UNAVAILABLE";
    default:
      return "DECLARED"; // unknown/no probe yet
  }
}

export interface CapabilityFilter {
  service?: string;
  environment?: string;
  domain?: string;
  actionType?: CapabilityClass;
}

export const CapabilityRegistry = {
  list(filter: CapabilityFilter = {}): CapabilityPublic[] {
    return DESCRIPTORS.filter((c) => {
      if (filter.service && c.serviceId !== filter.service) return false;
      if (filter.environment && c.environmentId !== filter.environment) return false;
      if (filter.domain && c.domain !== filter.domain) return false;
      if (filter.actionType && c.actionType !== filter.actionType) return false;
      return true;
    }).map((c) => ({ ...c, state: c.declaredState }));
  },
  get(id: string): CapabilityPublic | null {
    const c = BY_ID.get(id);
    return c ? { ...c, state: c.declaredState } : null;
  },
  descriptors(): CapabilityDescriptor[] {
    return DESCRIPTORS.slice();
  },
  isValidId(id: string): boolean {
    return BY_ID.has(id);
  },
};
