import { mkdir, readFile, writeFile } from "fs/promises";
import { dirname } from "path";
import { randomUUID } from "crypto";

import type { ConsoleOperator } from "@/types/auth";

export type OperationStatus =
  | "draft"
  | "validated"
  | "waiting_approval"
  | "approved"
  | "ready_for_execution"
  | "cancelled";
export type ApprovalStatus = "not_required" | "required" | "waiting" | "approved" | "cancelled";
export type RiskLevel = "low" | "medium" | "high" | "critical";

export interface OperationAuditEntry {
  audit_id: string;
  at: string;
  actor: string;
  transition: string;
  status: OperationStatus;
  details: Record<string, unknown>;
}

export interface OperationEvent {
  schema_version: "insight.operational_event.v1";
  event_type: string;
  service: "console";
  severity: "INFO" | "WARN" | "ERROR";
  timestamp: string;
  operation_id: string;
  correlation_id: string;
  previous_state?: string;
  current_state: string;
  target_service: string;
  target_resource: string;
  operator_id: string;
  metadata: Record<string, unknown>;
}

export interface OperationRecord {
  operation_id: string;
  operation_type: string;
  created_at: string;
  created_by: string;
  current_status: OperationStatus;
  approval_status: ApprovalStatus;
  risk_level: RiskLevel;
  target_service: string;
  target_resource: string;
  requested_action: string;
  preview_payload: Record<string, unknown>;
  impact_analysis: Record<string, unknown>;
  rollback_availability: string;
  execution_policy: Record<string, unknown>;
  correlation_id: string;
  operational_events: OperationEvent[];
  audit_trail: OperationAuditEntry[];
  permission_evaluation: Record<string, unknown>;
  dry_run?: Record<string, unknown>;
}

const STORE_PATH = process.env.CONSOLE_OPERATIONS_STORE ?? "/tmp/insight-console-operations.json";

async function readStore(): Promise<OperationRecord[]> {
  try {
    return JSON.parse(await readFile(STORE_PATH, "utf-8")) as OperationRecord[];
  } catch {
    return [];
  }
}

async function writeStore(records: OperationRecord[]) {
  await mkdir(dirname(STORE_PATH), { recursive: true });
  await writeFile(STORE_PATH, JSON.stringify(records.slice(-500), null, 2), "utf-8");
}

export async function listOperations(): Promise<OperationRecord[]> {
  return (await readStore()).sort((a, b) => b.created_at.localeCompare(a.created_at));
}

export async function createOperation(input: Record<string, unknown>, operator: ConsoleOperator): Promise<OperationRecord> {
  const now = new Date().toISOString();
  const operationId = `op-${now.replace(/[-:.]/g, "").slice(0, 15)}-${randomUUID().slice(0, 8)}`;
  const correlationId = `corr-${randomUUID()}`;
  const risk = riskLevel(input.risk_level);
  const targetService = stringOf(input.target_service, inferTargetService(input));
  const targetResource = stringOf(input.target_resource, "not-specified");
  const requiredPermission = stringOf(input.required_permission, "console.access");
  const permissionGranted = operator.role === "SuperAdmin" || operator.permissions.includes(requiredPermission as never);
  const impact = impactAnalysis(input, risk, targetService);
  const record: OperationRecord = {
    operation_id: operationId,
    operation_type: stringOf(input.operation_type, stringOf(input.action_id, "unknown")),
    created_at: now,
    created_by: operator.username ?? operator.displayName ?? operator.id,
    current_status: "waiting_approval",
    approval_status: "waiting",
    risk_level: risk,
    target_service: targetService,
    target_resource: targetResource,
    requested_action: stringOf(input.requested_action, stringOf(input.action_name, "unknown_action")),
    preview_payload: objectOf(input.preview_payload, input),
    impact_analysis: impact,
    rollback_availability: stringOf(input.rollback_availability, "rollback depends on operation-specific snapshot"),
    execution_policy: {
      execution_enabled: false,
      executable_in: "IOC-CONTROL-B2",
      requires_approval: true,
      requires_confirmation: true,
      direct_service_calls_allowed: false,
    },
    correlation_id: correlationId,
    operational_events: [],
    audit_trail: [],
    permission_evaluation: {
      current_user: operator.displayName,
      current_role: operator.role,
      required_permission: requiredPermission,
      granted: permissionGranted,
      denied: !permissionGranted,
      reason: permissionGranted ? "permission_granted_or_superadmin" : "required_permission_missing",
    },
  };
  append(record, "operation_created", "draft", "creation", operator, { input });
  append(record, "operation_validated", "validated", "validation", operator, { valid: true });
  append(record, "operation_permission_checked", "validated", "permission_check", operator, record.permission_evaluation);
  append(record, "operation_waiting_approval", "waiting_approval", "approval_required", operator, { approvers_required: risk === "critical" ? 2 : 1 });
  const records = await readStore();
  records.push(record);
  await writeStore(records);
  return record;
}

export async function dryRunOperation(operationId: string, operator: ConsoleOperator): Promise<OperationRecord> {
  const records = await readStore();
  const record = findOperation(records, operationId);
  record.dry_run = {
    expected_changes: ["operation would be queued for future executor", "canonical lifecycle events would be emitted"],
    resources_touched: [record.target_service, record.target_resource].filter(Boolean),
    events_expected: ["operation_ready_for_execution", `${record.operation_type}_requested`],
    rollback_strategy: record.rollback_availability,
    warnings: record.risk_level === "critical" ? ["critical operation requires explicit multi-approval in B2"] : [],
    blocking_conditions: ["execution disabled until IOC-CONTROL-B2"],
    production_state_changed: false,
  };
  append(record, "operation_dryrun_completed", record.current_status, "dry_run", operator, record.dry_run);
  await writeStore(records);
  return record;
}

export async function approveOperation(operationId: string, operator: ConsoleOperator): Promise<OperationRecord> {
  const records = await readStore();
  const record = findOperation(records, operationId);
  append(record, "operation_approved", "approved", "approval", operator, { approved_by: operator.id });
  record.approval_status = "approved";
  append(record, "operation_ready_for_execution", "ready_for_execution", "ready", operator, { execution_enabled: false, executable_in: "IOC-CONTROL-B2" });
  await writeStore(records);
  return record;
}

export async function cancelOperation(operationId: string, operator: ConsoleOperator): Promise<OperationRecord> {
  const records = await readStore();
  const record = findOperation(records, operationId);
  record.approval_status = "cancelled";
  append(record, "operation_cancelled", "cancelled", "cancellation", operator, { cancelled_by: operator.id });
  await writeStore(records);
  return record;
}

function findOperation(records: OperationRecord[], operationId: string): OperationRecord {
  const record = records.find((item) => item.operation_id === operationId);
  if (!record) throw new Error("operation_not_found");
  return record;
}

function append(record: OperationRecord, eventType: string, nextStatus: OperationStatus, transition: string, operator: ConsoleOperator, details: Record<string, unknown>) {
  const now = new Date().toISOString();
  const previous = record.current_status;
  record.current_status = nextStatus;
  record.audit_trail.push({
    audit_id: `audit-${randomUUID()}`,
    at: now,
    actor: operator.username ?? operator.displayName ?? operator.id,
    transition,
    status: nextStatus,
    details,
  });
  record.operational_events.push({
    schema_version: "insight.operational_event.v1",
    event_type: eventType,
    service: "console",
    severity: "INFO",
    timestamp: now,
    operation_id: record.operation_id,
    correlation_id: record.correlation_id,
    previous_state: previous,
    current_state: nextStatus,
    target_service: record.target_service,
    target_resource: record.target_resource,
    operator_id: operator.id,
    metadata: details,
  });
}

function impactAnalysis(input: Record<string, unknown>, risk: RiskLevel, targetService: string) {
  const affectedServices = arrayOf(input.affected_services, targetService);
  return {
    affected_services: affectedServices,
    affected_missions: arrayOf(input.affected_missions),
    affected_providers: arrayOf(input.affected_providers),
    affected_datasets: arrayOf(input.affected_datasets),
    affected_reports: arrayOf(input.affected_reports),
    affected_signals: arrayOf(input.affected_signals),
    affected_behaviors: arrayOf(input.affected_behaviors),
    estimated_duration: stringOf(input.estimated_duration, risk === "critical" ? "requires operator estimate" : "short control-plane workflow"),
    operational_risk: risk,
    rollback_availability: stringOf(input.rollback_availability, "operation-specific rollback required"),
  };
}

function inferTargetService(input: Record<string, unknown>) {
  const services = arrayOf(input.affected_services);
  return services[0] ?? stringOf(input.domain, "console").toLowerCase();
}

function riskLevel(value: unknown): RiskLevel {
  return ["low", "medium", "high", "critical"].includes(String(value)) ? String(value) as RiskLevel : "medium";
}

function stringOf(value: unknown, fallback: string) {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function objectOf(value: unknown, fallback: Record<string, unknown>) {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : fallback;
}

function arrayOf(value: unknown, fallback?: string) {
  if (Array.isArray(value)) return value.map(String).filter(Boolean);
  if (typeof value === "string" && value) return [value];
  return fallback ? [fallback] : [];
}
