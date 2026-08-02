// Publication-domain status pills — Sprint 4.5.
// Single mapping for ticket, candidate and provider statuses so every
// page colors states identically.

import { Badge } from "@/components/ui/badge";

const TICKET_VARIANT: Record<string, "default" | "success" | "warning" | "destructive" | "outline"> = {
  OPEN: "warning",
  UNDER_REVIEW: "default",
  APPROVED: "success",
  PUBLISHED: "success",
  REJECTED: "destructive",
};

const CANDIDATE_VARIANT: Record<string, "default" | "success" | "warning" | "destructive" | "outline"> = {
  PUBLISHED: "success",
  SUPPRESSED: "warning",
  INVALID: "destructive",
  FAILED: "destructive",
  TICKETED: "outline",
};

const PROVIDER_VARIANT: Record<string, "default" | "success" | "warning" | "destructive" | "outline"> = {
  healthy: "success",
  degraded: "warning",
  offline: "destructive",
};

export function TicketStatusBadge({ status }: { status: string }) {
  return <Badge variant={TICKET_VARIANT[status] ?? "outline"}>{status}</Badge>;
}

export function CandidateStatusBadge({ status }: { status: string }) {
  return <Badge variant={CANDIDATE_VARIANT[status] ?? "outline"}>{status}</Badge>;
}

export function ProviderStatusBadge({ status }: { status: string }) {
  return <Badge variant={PROVIDER_VARIANT[status] ?? "outline"}>● {status}</Badge>;
}
