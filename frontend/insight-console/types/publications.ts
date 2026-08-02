// Publication-control wire types — Sprint 4.5.
//
// These mirror the Nexus admin API JSON (snake_case, additive-only;
// tagged on the Go domain structs in insight-nexus
// internal/domain/publication + persona). The Console renders these
// verbatim — explainability fields are NEVER recomputed client-side.

export type TicketStatus =
  | "OPEN"
  | "UNDER_REVIEW"
  | "APPROVED"
  | "REJECTED"
  | "PUBLISHED";

export type CandidateStatus =
  | "PUBLISHED"
  | "SUPPRESSED"
  | "INVALID"
  | "FAILED"
  | "TICKETED";

export interface PublicationTicket {
  id: string;
  agent_id: string;
  agent_name: string;
  trend_ids: string[] | null;
  cluster_id: string;
  context: Record<string, unknown> | null;
  publication_reason: string;
  suggested_title: string;
  suggested_summary: string;
  evidence: string[] | null;
  priority: string;
  match_id: string;
  status: TicketStatus;
  reviewed_by: string;
  reviewed_at: string | null;
  published_by: string;
  published_at: string | null;
  created_at: string;
}

export interface PublicationCandidate {
  id: string;
  draft_id: string;
  agent_id: string;
  agent_name: string;
  trend_ids: string[] | null;
  cluster_id: string;
  decision_id: string;
  publication_reason: string;
  prompt_version: string;
  provider: string;
  model: string;
  fallback_used: boolean;
  fallback_chain: string[] | null;
  draft_version: number;
  title: string;
  summary: string;
  highlights: string[] | null;
  tags: string[] | null;
  chart_hints: string[] | null;
  match_id: string;
  status: CandidateStatus;
  status_reason: string;
  social_post_id: string;
  created_at: string;
  published_at: string | null;
}

export interface AgentPersona {
  slug: string;
  social_author_id: string;
  style: string;
  tone: string;
  expertise: string;
  restrictions: string[] | null;
  posting_behavior: string;
  updated_at: string;
}

/** llmrouter.HealthManager snapshot entry. */
export interface ProviderSnapshot {
  provider: string;
  status: "healthy" | "degraded" | "offline";
  last_checked: string;
  last_error?: string;
}

export interface NexusAuditEvent {
  id: string;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  reason: string;
  created_at: string;
}

export interface NexusAgent {
  id: string;
  name: string;
  active: boolean;
  specialty?: string;
  trend_types?: string[];
  posting_rules?: Record<string, unknown>;
  system_context?: string;
  queue?: string;
  created_at?: string;
  updated_at?: string;
}

/** Per-agent candidate outcome counts (agent-metrics endpoint). */
export type AgentOutcomeCounts = Record<string, Record<string, number>>;
