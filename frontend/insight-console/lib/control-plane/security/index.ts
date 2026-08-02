// Console security foundation public surface (CONSOLE-SECURITY-A0). SERVER-ONLY.
// Route handlers import from here; the browser never imports this module.

export {
  resolveOperatorContext,
  operatorContextFromOperator,
  buildOperatorContext,
  assertNoClientActor,
  type OperatorContext,
} from "@/lib/control-plane/security/operator-context";
export {
  resolveAdminRequestContext,
  type AdministrativeRequestContext,
  type SourceSurface,
} from "@/lib/control-plane/security/request-context";
export {
  authorize,
  type AuthorizationDecision,
  type AuthorizationTarget,
} from "@/lib/control-plane/security/authorization";
export {
  resolveDelegation,
  rejectSelfDelegation,
  assertOperatorPreserved,
  type DelegationContext,
} from "@/lib/control-plane/security/delegation";
export { AdministrativeAudit, type AuditWriteResult } from "@/lib/control-plane/security/audit/writer";
export {
  buildAuditEvent,
  safeMetadata,
  type AdministrativeAuditEvent,
  type AuditStatus,
} from "@/lib/control-plane/security/audit/model";
export {
  getAuditRepository,
  __resetAuditRepository,
} from "@/lib/control-plane/security/audit/factory";
export {
  InMemoryAuditRepository,
  PostgresAuditRepository,
  type AuditRepository,
  type AuditQueryFilter,
  type AuditPage,
} from "@/lib/control-plane/security/audit/repository";
export { GatewayAuditRepository } from "@/lib/control-plane/security/audit/gateway-sink";
export { observeSecurity } from "@/lib/control-plane/security/observability";
