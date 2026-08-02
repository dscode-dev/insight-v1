// Investigation + Timeline composition services (CONSOLE-SOCIAL-A2). SERVER-ONLY.
//
// Server-side cross-domain composition — the browser never joins Social + Gateway.
// Each panel/source is independently loaded, failure-isolated (allSettled), with
// explicit source attribution and honest partial state. Domain ownership stays
// explicit (Social adapter vs Gateway Trust & Safety vs audit reader).

import { SocialControlPlane, type SocialReadContext } from "@/lib/control-plane/adapters/social";
import { GatewayTrustSafety } from "@/lib/control-plane/adapters/trust-safety";
import { getAuditRepository } from "@/lib/control-plane/security/audit/factory";

export type EntityType = "user" | "agent" | "post" | "comment" | "community" | "report";

type PanelState = "available" | "unavailable";
interface Panel<T> {
  state: PanelState;
  data: T | null;
  error?: string;
}

async function panel<T>(run: () => Promise<T>): Promise<Panel<T>> {
  try {
    return { state: "available", data: await run() };
  } catch (e) {
    return { state: "unavailable", data: null, error: e instanceof Error ? e.message : "error" };
  }
}

// Map an investigation entity to a moderation/audit target descriptor.
function targetFor(entityType: EntityType, id: string) {
  // moderation target_type vocabulary: post | comment | user
  const t = entityType === "agent" ? "user" : entityType; // agents share the actor space
  return { targetType: t, targetId: id };
}

export const InvestigationService = {
  async investigate(ctx: SocialReadContext, entityType: EntityType, entityId: string) {
    const summary = panel(() => {
      switch (entityType) {
        case "user": return SocialControlPlane.getUser(ctx, entityId);
        case "agent": return SocialControlPlane.getAgent(ctx, entityId);
        case "post": return SocialControlPlane.getPost(ctx, entityId);
        case "comment": return SocialControlPlane.getComment(ctx, entityId);
        case "community": return SocialControlPlane.getCommunity(ctx, entityId);
        case "report": return GatewayTrustSafety.reports(`limit=200`) as Promise<unknown>;
      }
    });

    const timelineType = entityType === "comment" || entityType === "community" || entityType === "report" ? null : entityType;
    const timeline = timelineType
      ? panel(() => SocialControlPlane.timeline(ctx, timelineType, entityId, "100"))
      : Promise.resolve<Panel<unknown>>({ state: "available", data: { items: [] } });

    const relationships =
      entityType === "user" || entityType === "agent"
        ? panel(() => SocialControlPlane.relationships(ctx, entityType, entityId))
        : Promise.resolve<Panel<unknown>>({ state: "available", data: { relationships: [] } });

    const boosts =
      entityType === "post"
        ? panel(() => SocialControlPlane.listBoosts(ctx, { post_id: entityId }))
        : entityType === "user"
          ? panel(() => SocialControlPlane.listBoosts(ctx, { user_id: entityId }))
          : Promise.resolve<Panel<unknown>>({ state: "available", data: { items: [] } });

    const trustTarget = targetFor(entityType, entityId);
    const trust = entityType === "report"
      ? Promise.resolve<Panel<unknown>>({ state: "available", data: null })
      : panel(() => GatewayTrustSafety.forTarget(trustTarget));

    const audit = panel(async () => {
      const page = await getAuditRepository().query({ resourceId: entityId, limit: 25 });
      return { items: page.items };
    });

    const [summaryR, timelineR, relationshipsR, boostsR, trustR, auditR] = await Promise.all([
      summary, timeline, relationships, boosts, trust, audit,
    ]);

    const sources = [
      { panel: "summary", state: summaryR.state, source: "insight-social" },
      { panel: "timeline", state: timelineR.state, source: "insight-social" },
      { panel: "relationships", state: relationshipsR.state, source: "insight-social" },
      { panel: "amplification", state: boostsR.state, source: "insight-social" },
      { panel: "trust_safety", state: trustR.state, source: "insight-gateway" },
      { panel: "administrative_audit", state: auditR.state, source: "insight-gateway/operator_audit_log" },
    ];
    const partial = sources.some((s) => s.state !== "available");

    return {
      entity: { type: entityType, id: entityId },
      partial,
      sources,
      panels: {
        summary: summaryR,
        timeline: timelineR,
        relationships: relationshipsR,
        amplification: boostsR,
        trust_safety: trustR,
        administrative_audit: auditR,
      },
    };
  },
};

// ---- Correlated Timeline (multi-source, provenance-tagged) ----

interface TimelineItem {
  id: string;
  at: string;
  kind: string;
  domain: string;
  provenance: "DURABLE_ROW_PROJECTION" | "MODERATION_RECORD" | "ADMINISTRATIVE_AUDIT";
  target: { type: string; id: string } | null;
  summary: string;
  correlation_id: string | null;
}

export const TimelineService = {
  async timeline(ctx: SocialReadContext, entityType: EntityType, entityId: string) {
    const sources: Array<{ source: string; state: PanelState; error?: string }> = [];
    const items: TimelineItem[] = [];

    // 1. Social durable-row projection.
    if (entityType === "user" || entityType === "agent" || entityType === "post") {
      try {
        const soc = (await SocialControlPlane.timeline(ctx, entityType, entityId, "200")) as { items?: Array<Record<string, unknown>> };
        for (const it of soc.items ?? []) {
          items.push({
            id: String(it["id"]), at: String(it["at"]), kind: String(it["kind"]), domain: "social",
            provenance: "DURABLE_ROW_PROJECTION",
            target: it["target"] ? { type: String((it["target"] as Record<string, unknown>)["type"]), id: String((it["target"] as Record<string, unknown>)["id"]) } : null,
            summary: String(it["kind"]), correlation_id: null,
          });
        }
        sources.push({ source: "insight-social", state: "available" });
      } catch (e) {
        sources.push({ source: "insight-social", state: "unavailable", error: e instanceof Error ? e.message : "error" });
      }
    }

    // 2. Gateway moderation records for the target.
    if (entityType !== "report" && entityType !== "community") {
      try {
        const { actions } = await GatewayTrustSafety.forTarget(targetFor(entityType, entityId));
        for (const a of actions as Array<Record<string, unknown>>) {
          items.push({
            id: String(a["id"]), at: String(a["created_at"]), kind: `moderation:${String(a["action"])}`,
            domain: "gateway", provenance: "MODERATION_RECORD",
            target: { type: String(a["target_type"]), id: String(a["target_id"]) },
            summary: String(a["action"]), correlation_id: null,
          });
        }
        sources.push({ source: "insight-gateway/moderation", state: "available" });
      } catch (e) {
        sources.push({ source: "insight-gateway/moderation", state: "unavailable", error: e instanceof Error ? e.message : "error" });
      }
    }

    // 3. Administrative audit events referencing the resource.
    try {
      const page = await getAuditRepository().query({ resourceId: entityId, limit: 50 });
      for (const ev of page.items) {
        items.push({
          id: ev.eventId, at: ev.occurredAt, kind: `audit:${ev.action.capability}`, domain: "audit",
          provenance: "ADMINISTRATIVE_AUDIT",
          target: ev.target.resourceId ? { type: ev.target.resourceType ?? "", id: ev.target.resourceId } : null,
          summary: `${ev.action.capability} ${ev.outcome.status}`, correlation_id: ev.correlationId,
        });
      }
      sources.push({ source: "operator_audit_log", state: "available" });
    } catch (e) {
      sources.push({ source: "operator_audit_log", state: "unavailable", error: e instanceof Error ? e.message : "error" });
    }

    // Deterministic ordering: time desc, then id.
    items.sort((a, b) => (b.at.localeCompare(a.at) || b.id.localeCompare(a.id)));
    return {
      entity: { type: entityType, id: entityId },
      partial: sources.some((s) => s.state !== "available"),
      sources,
      items,
    };
  },
};
