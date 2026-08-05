/**
 * Environment configuration, validated once at boot.
 *
 * Fail-fast by design: a missing signing secret or Gateway URL must stop
 * the process at startup, not produce a service that silently accepts
 * unsigned identity envelopes or 503s every request.
 */
import { z } from 'zod';

const schema = z.object({
  PORT: z.coerce.number().int().positive().default(3002),
  HOST: z.string().default('0.0.0.0'),

  /**
   * Shared secret used to verify the identity envelope the Next.js BFF
   * signs. This is the ONLY thing standing between "identity resolved
   * server-side by the console" and "identity asserted by whoever can
   * reach this port", so it is required with a real minimum length —
   * never defaulted.
   */
  CONSOLE_API_SIGNING_SECRET: z.string().min(32),

  /** Robozão Gateway — owner of operator identity/session/roles. */
  ROBOZAO_GATEWAY_URL: z.string().url(),

  /** Seconds a resolved session stays cached. Short by intent. */
  SESSION_CACHE_TTL_SECONDS: z.coerce.number().int().positive().max(300).default(30),

  /** Max cached sessions before LRU eviction. */
  SESSION_CACHE_MAX_ENTRIES: z.coerce.number().int().positive().default(2048),

  /** Upstream timeout for Gateway/Explorer/Atlas calls, milliseconds. */
  UPSTREAM_TIMEOUT_MS: z.coerce.number().int().positive().default(10_000),

  /** How often realtime channels poll upstream, milliseconds. */
  REALTIME_POLL_INTERVAL_MS: z.coerce.number().int().min(1000).default(5000),

  EXPLORER_API_BASE_URL: z.string().url().default('http://insight-explorer:8090'),
  EXPLORER_OPS_TOKEN: z.string().default(''),
  ATLAS_API_BASE_URL: z.string().url().default('http://atlas:8085'),
  ATLAS_INTERNAL_TOKEN: z.string().default(''),
});

export type AppConfig = z.infer<typeof schema>;

let cached: AppConfig | null = null;

export function loadConfig(env: NodeJS.ProcessEnv = process.env): AppConfig {
  const parsed = schema.safeParse(env);
  if (!parsed.success) {
    const detail = parsed.error.issues
      .map((issue) => `${issue.path.join('.')}: ${issue.message}`)
      .join('; ');
    throw new Error(`invalid insight-console-api configuration — ${detail}`);
  }
  return parsed.data;
}

export function getConfig(): AppConfig {
  if (cached === null) {
    cached = loadConfig();
  }
  return cached;
}

/** Test seam — never called in production. */
export function resetConfigForTests(): void {
  cached = null;
}
