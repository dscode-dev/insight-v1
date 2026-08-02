// Control Plane server configuration (CONSOLE-FOUNDATION-A).
//
// SERVER-ONLY. This is the single place where privileged upstream URLs and
// internal tokens are read from the environment. Nothing here is ever
// serialized to the browser — the registries derive *public* read models that
// strip endpoints and tokens (see registries/services.ts `toPublicService`).
//
// Design (ADR-0001/0003/0008): topology + secrets are server-owned. The Console
// BFF authenticates through this config; the browser holds only its session
// cookie. We validate mandatory config and mark optional upstreams explicitly
// unavailable rather than silently substituting a production host.

import { z } from "zod";

/** A configured upstream the Console BFF may call server-side. */
export interface UpstreamConfig {
  /** Base URL, normalized without a trailing slash. Empty string = not configured. */
  readonly baseUrl: string;
  /** True when a usable base URL is present. */
  readonly configured: boolean;
  /** Internal/service token, if this upstream needs one. NEVER serialized. */
  readonly token?: string;
}

const urlOrEmpty = z
  .string()
  .trim()
  .transform((v) => v.replace(/\/+$/, ""))
  .optional()
  .default("");

// We validate shapes but never *require* optional upstreams — an absent Nexus
// URL means "Console has no configured route to Nexus", not a crash.
const schema = z.object({
  ADMIN_API_BASE_URL: z
    .string()
    .trim()
    .transform((v) => v.replace(/\/+$/, ""))
    .default("https://insight-api.konohalabs.com.br/v1"),
  ADMIN_API_INTERNAL_TOKEN: z.string().optional().default(""),
  ATLAS_API_BASE_URL: urlOrEmpty,
  ATLAS_INTERNAL_TOKEN: z.string().optional().default(""),
  EXPLORER_API_BASE_URL: urlOrEmpty,
  ROBOZAO_GATEWAY_URL: urlOrEmpty,
  // Nexus has no default: if unset, Nexus is a KNOWN service the Console cannot
  // directly reach (configured=false), never a guessed production host.
  NEXUS_API_BASE_URL: urlOrEmpty,
  NODE_ENV: z.string().optional().default("development"),
});

export interface ControlPlaneConfig {
  readonly gateway: UpstreamConfig; // cloud gateway (admin/console surface)
  readonly atlas: UpstreamConfig; // robozão intelligence
  readonly explorer: UpstreamConfig; // robozão data collection
  readonly robozaoGateway: UpstreamConfig; // robozão operations protocol
  readonly nexus: UpstreamConfig; // robozão publication engine
  readonly isProduction: boolean;
  /** Mandatory-config problems found at load. Reads may still degrade, not crash. */
  readonly configErrors: string[];
}

function upstream(baseUrl: string, token?: string): UpstreamConfig {
  const trimmed = (baseUrl ?? "").trim();
  return {
    baseUrl: trimmed,
    configured: trimmed.length > 0,
    ...(token ? { token } : {}),
  };
}

let cached: ControlPlaneConfig | null = null;

/** Load + validate control-plane config once per process. */
export function controlPlaneConfig(): ControlPlaneConfig {
  if (cached) return cached;
  const parsed = schema.safeParse(process.env);
  const env = parsed.success ? parsed.data : schema.parse({});
  const isProduction = env.NODE_ENV === "production";

  const configErrors: string[] = [];
  if (!parsed.success) {
    configErrors.push(`invalid_control_plane_env: ${parsed.error.issues.length} issue(s)`);
  }
  // In production the gateway service token is required for the admin surface.
  if (isProduction && !env.ADMIN_API_INTERNAL_TOKEN) {
    configErrors.push("ADMIN_API_INTERNAL_TOKEN missing (admin surface will be unavailable)");
  }

  cached = {
    gateway: upstream(env.ADMIN_API_BASE_URL, env.ADMIN_API_INTERNAL_TOKEN || undefined),
    atlas: upstream(env.ATLAS_API_BASE_URL, env.ATLAS_INTERNAL_TOKEN || undefined),
    explorer: upstream(env.EXPLORER_API_BASE_URL),
    robozaoGateway: upstream(env.ROBOZAO_GATEWAY_URL),
    nexus: upstream(env.NEXUS_API_BASE_URL),
    isProduction,
    configErrors,
  };
  return cached;
}

/** Test-only: drop the memoized config so env changes take effect. */
export function __resetControlPlaneConfig(): void {
  cached = null;
}
