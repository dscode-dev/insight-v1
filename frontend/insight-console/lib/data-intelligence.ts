// Data Intelligence surfaces, via the Insight Control Plane. SERVER-ONLY.
//
// WHAT CHANGED. This module used to call Explorer and Atlas directly,
// which is why the console had to hold EXPLORER_OPS_TOKEN and
// ATLAS_INTERNAL_TOKEN. insight-context.md v2.0 says the console "nunca
// acessa diretamente os demais serviços — toda comunicação ocorre
// através do Insight Control Plane", so both calls now go there and
// neither token exists in this process any more.
//
// The Atlas routing rule moved WITH the calls, into
// `src/data-intelligence/path-policy.ts` on the Control Plane. It is
// knowledge about Atlas's two routers (`/atlas/*` versus
// `/v1/internal/intelligence/*`), and it belongs next to the service
// that talks to Atlas rather than in a frontend module.

import { consoleApiCall } from "@/lib/control-plane/adapters/console-api";

/**
 * Call an Explorer surface.
 *
 * The actor is deliberately NOT a parameter any more: the Control Plane
 * derives the operator from the session it already resolved and
 * forwards it as X-Operator. A caller-supplied actor would be a second,
 * spoofable source of attribution for Explorer's own audit log.
 */
export async function explorerCall(
  path: string,
  method: string,
  body: unknown,
): Promise<Response> {
  return consoleApiCall(
    `data-intelligence/${path.replace(/^\/+/, "")}`,
    method,
    body,
  );
}

/** Call an Atlas intelligence surface through the Control Plane. */
export async function atlasIntelligenceCall(
  path: string,
  method: string,
  body: unknown,
): Promise<Response> {
  return consoleApiCall(
    `data-intelligence/atlas/${path.replace(/^\/+/, "")}`,
    method,
    body,
  );
}
