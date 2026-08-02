// Control Plane operational observability (CONSOLE-FOUNDATION-A, Stage 10).
//
// Structured, non-sensitive logs for the foundation itself. This is OPERATIONAL
// telemetry, NOT the canonical administrative audit spine — the audit found the
// Operation domain never reaches the real audit spine, and this layer does not
// pretend otherwise. Canonical operator audit is CONSOLE-SECURITY-A0.
//
// We deliberately reuse the existing console-metrics counter convention rather
// than inventing a telemetry universe. Logs are single-line JSON on stdout,
// correlation-id aware, and never include tokens/URLs/PII.

export type ControlPlaneEvent =
  | "adapter_request_started"
  | "adapter_request_completed"
  | "adapter_request_failed"
  | "adapter_request_timeout"
  | "registry_resolution_failed"
  | "capability_unsupported_requested"
  | "platform_snapshot_generated"
  | "platform_snapshot_partial";

export interface ObserveFields {
  service?: string;
  environment?: string;
  operation?: string;
  code?: string;
  latencyMs?: number;
  correlationId?: string;
  sources?: number;
  degradedSources?: number;
}

const SEVERITY: Record<ControlPlaneEvent, "INFO" | "WARN" | "ERROR"> = {
  adapter_request_started: "INFO",
  adapter_request_completed: "INFO",
  adapter_request_failed: "ERROR",
  adapter_request_timeout: "WARN",
  registry_resolution_failed: "WARN",
  capability_unsupported_requested: "WARN",
  platform_snapshot_generated: "INFO",
  platform_snapshot_partial: "WARN",
};

/** Emit one structured control-plane telemetry line. Never throws. */
export function observe(event: ControlPlaneEvent, fields: ObserveFields = {}): void {
  try {
    const line = {
      layer: "control-plane",
      event,
      severity: SEVERITY[event],
      ts: new Date().toISOString(),
      ...fields,
    };
    const sink = SEVERITY[event] === "ERROR" ? console.error : console.log;
    sink(`[console:control-plane] ${JSON.stringify(line)}`);
  } catch {
    /* observability must never break a request */
  }
}
