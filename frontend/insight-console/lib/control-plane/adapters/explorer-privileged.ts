// Operator-bound Explorer adapter. SERVER-ONLY.
//
// WHAT THIS IS NOW. Its original job was deriving Explorer's
// `X-Operator` server-side from the verified OperatorContext, so the
// browser could never control attribution. That derivation moved to the
// Insight Control Plane, which resolves the operator from the session
// itself and forwards it — the console does not send an actor at all
// any more, which is a stronger guarantee than sending a trustworthy
// one: there is no field to spoof.
//
// The seam is kept for its security telemetry. Every privileged
// Explorer flow still passes through one place that observes it, and
// the console's audit spine reads those events.

import { explorerCall } from "@/lib/data-intelligence";
import { observeSecurity } from "@/lib/control-plane/security/observability";
import type { OperatorContext } from "@/lib/control-plane/security/operator-context";

export async function explorerPrivilegedCall(
  operator: OperatorContext,
  path: string,
  method: string,
  body: unknown,
): Promise<Response> {
  observeSecurity("privileged_adapter_request", {
    operatorId: operator.operatorId,
    service: "explorer",
    correlationId: operator.correlationId,
  });
  try {
    return await explorerCall(path, method, body);
  } catch (err) {
    observeSecurity("privileged_adapter_failure", {
      operatorId: operator.operatorId,
      service: "explorer",
      correlationId: operator.correlationId,
    });
    throw err;
  }
}
