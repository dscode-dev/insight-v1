// Audit repository factory (CONSOLE-SECURITY-A1). SERVER-ONLY.
//
// PRODUCTION DEFAULT = the durable Gateway sink (canonical operator_audit_log).
// There is NO silent in-memory production fallback: memory is used ONLY when
// explicitly requested (`CONSOLE_AUDIT_MODE=memory`, dev/tests). A direct
// Console-owned Postgres store remains available via CONSOLE_AUDIT_DATABASE_URL.

import {
  InMemoryAuditRepository,
  PostgresAuditRepository,
  type AuditRepository,
} from "@/lib/control-plane/security/audit/repository";
import { GatewayAuditRepository } from "@/lib/control-plane/security/audit/gateway-sink";

let cached: AuditRepository | null = null;

export function getAuditRepository(): AuditRepository {
  if (cached) return cached;
  const mode = process.env.CONSOLE_AUDIT_MODE;
  if (mode === "memory") {
    cached = new InMemoryAuditRepository();
  } else if (process.env.CONSOLE_AUDIT_DATABASE_URL) {
    cached = new PostgresAuditRepository(process.env.CONSOLE_AUDIT_DATABASE_URL);
  } else {
    // Durable primary path: write/read the canonical Gateway spine.
    cached = new GatewayAuditRepository();
  }
  return cached;
}

export function __resetAuditRepository(): void {
  cached = null;
}
