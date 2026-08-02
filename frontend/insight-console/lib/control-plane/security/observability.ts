// Security observability (CONSOLE-SECURITY-A0, Stage 16). SERVER-ONLY.
//
// OPERATIONAL telemetry for the security foundation — deliberately DISTINCT from
// the canonical administrative audit (which is durable, tamper-evident, and
// answers who/what/why). A log line is NOT canonical audit. Never logs tokens,
// cookies, credentials, or Authorization headers.

export type SecurityEvent =
  | "operator_context_resolved"
  | "operator_context_failed"
  | "authorization_allowed"
  | "authorization_denied"
  | "legacy_attribution_ignored"
  | "audit_write_succeeded"
  | "audit_write_failed"
  | "audit_reconciliation_needed"
  | "delegation_rejected"
  | "capability_unauthorized_request"
  | "privileged_adapter_request"
  | "privileged_adapter_failure";

export interface SecurityFields {
  operatorId?: string;
  capability?: string;
  service?: string;
  environment?: string;
  reasonCode?: string;
  correlationId?: string | null;
  durable?: boolean;
  field?: string;
}

const SEVERITY: Record<SecurityEvent, "INFO" | "WARN" | "ERROR"> = {
  operator_context_resolved: "INFO",
  operator_context_failed: "WARN",
  authorization_allowed: "INFO",
  authorization_denied: "WARN",
  legacy_attribution_ignored: "WARN",
  audit_write_succeeded: "INFO",
  audit_write_failed: "ERROR",
  audit_reconciliation_needed: "ERROR",
  delegation_rejected: "WARN",
  capability_unauthorized_request: "WARN",
  privileged_adapter_request: "INFO",
  privileged_adapter_failure: "ERROR",
};

/** Emit one structured security-telemetry line. Never throws, never leaks secrets. */
export function observeSecurity(event: SecurityEvent, fields: SecurityFields = {}): void {
  try {
    const line = { layer: "console-security", event, severity: SEVERITY[event], ts: new Date().toISOString(), ...fields };
    const sink = SEVERITY[event] === "ERROR" ? console.error : console.log;
    sink(`[console:security] ${JSON.stringify(line)}`);
  } catch {
    /* telemetry must never break a request */
  }
}
