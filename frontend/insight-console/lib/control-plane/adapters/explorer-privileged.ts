// Operator-bound Explorer privileged adapter (CONSOLE-SECURITY-A1, Stage 10).
// SERVER-ONLY.
//
// Closes the SECURITY-A0 debt: Explorer's `X-Operator` is now derived SERVER-SIDE
// from the verified OperatorContext and can never be controlled by the browser.
// Correlation is propagated. This is a thin, typed containment over the existing
// Explorer client — Explorer intelligence logic is untouched, and Atlas (frozen,
// read-only, service-token) is deliberately NOT routed here.
//
// HONEST NOTE: Explorer does not currently *verify* X-Operator — it is attribution
// metadata, not authentication. This adapter guarantees the value is trustworthy
// on the Console side (server-derived) and contains the flow behind one seam;
// stronger Explorer-side operator verification is recorded as future debt.

import { explorerCall } from "@/lib/data-intelligence";
import { observeSecurity } from "@/lib/control-plane/security/observability";
import type { OperatorContext } from "@/lib/control-plane/security/operator-context";

export async function explorerPrivilegedCall(
  operator: OperatorContext,
  path: string,
  method: string,
  body: unknown,
): Promise<Response> {
  // Server-derived attribution ONLY (username??id). Never a client value.
  const actor = operator.operatorUsername ?? operator.operatorId;
  observeSecurity("privileged_adapter_request", {
    operatorId: operator.operatorId,
    service: "explorer",
    correlationId: operator.correlationId,
  });
  try {
    return await explorerCall(path, method, body, actor, operator.correlationId ?? undefined);
  } catch (err) {
    observeSecurity("privileged_adapter_failure", {
      operatorId: operator.operatorId,
      service: "explorer",
      correlationId: operator.correlationId,
    });
    throw err;
  }
}
