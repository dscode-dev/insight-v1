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
   * The Control Plane's own database. It is authority over
   * administrative identity — operators, sessions, RBAC, the audit
   * spine — so this is required, not defaulted: a Control Plane that
   * boots without it can authenticate nobody.
   */
  CONTROL_PLANE_DATABASE_URL: z.string().min(1),
  DATABASE_POOL_SIZE: z.coerce.number().int().positive().max(50).default(10),

  /** Apply migrations/*.sql at boot. Off in production by default. */
  AUTO_APPLY_MIGRATIONS: z
    .enum(['true', 'false'])
    .default('false')
    .transform((value) => value === 'true'),

  /** How long an issued operator session lives. */
  SESSION_TTL_HOURS: z.coerce.number().int().positive().max(72).default(8),

  /**
   * Node Agent (Robozão) — machine state, containers, controlled
   * deploy. NOT an identity provider: insight-context.md v2.0 assigns
   * operator auth to the Control Plane, and the Node Agent explicitly
   * "nunca deve oferecer proxy HTTP".
   */
  ROBOZAO_GATEWAY_URL: z.string().url(),
  /**
   * Segredo compartilhado com o Node Agent. Este salto é
   * serviço-a-serviço: o Control Plane já autenticou a pessoa, e o Node
   * Agent não é um segundo provedor de identidade. Vazio = o Node Agent
   * cai no caminho legado (validar sessão no gateway público), que
   * devolve 401 para sessões do Control Plane.
   */
  NODE_AGENT_TOKEN: z.string().default(''),

  /**
   * Seconds a resolved session stays cached.
   *
   * This is the ONLY staleness window for revocation: resolveSession
   * enforces expiry, revocation and the operator's active flag in SQL,
   * so a logged-out or deactivated operator keeps working for at most
   * this long. Short by intent.
   */
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
  /** Empty = the Control Plane has no route to it, not a crash. */
  NEXUS_API_BASE_URL: z.string().default(''),
  /**
   * Service-to-service secret for the Nexus admin API.
   *
   * Same value as NODE_AGENT_TOKEN in the deployment: both internal
   * services accept the Control Plane on the same hop, and giving them
   * separate secrets to rotate independently buys nothing while the
   * Control Plane is the only caller of either.
   *
   * Empty = Nexus screens report unavailable. It is NOT a boot failure:
   * the rest of the console must keep working.
   */
  NEXUS_CONTROL_PLANE_TOKEN: z.string().default(''),
  /**
   * Insight Social's administrative surface, reached DIRECTLY.
   *
   * Not through the Gateway: insight-context.md v2.0 excludes the Gateway
   * from administration and the console, and routing Social's admin traffic
   * through it made the Gateway hold this token too.
   *
   * Empty = the Social screens report unavailable. Not a boot failure — the
   * rest of the console must keep working when the Google Cloud plane is
   * unreachable.
   */
  SOCIAL_CONSOLE_BASE_URL: z.string().default(''),
  SOCIAL_OPS_TOKEN: z.string().default(''),
  ANVIL_API_BASE_URL: z.string().default(''),
  /**
   * Cloud Gateway (Product plane). The Control Plane is the ONLY thing
   * that reaches it on an operator's behalf, so its internal token
   * lives here rather than in the console.
   */
  ADMIN_API_BASE_URL: z.string().default(''),
  ADMIN_API_INTERNAL_TOKEN: z.string().default(''),
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
