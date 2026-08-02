// Auth activity (Auth-A Part 11) — server-side only, READ-ONLY.
//
// Reads the LIVE auth_* counters the Gateway exposes at /metrics (Prometheus
// text exposition) and shapes them for the Console's Authentication section.
// No mocks, no mutations: the Console only observes. The Gateway is the source
// of truth; we never touch its DB directly.

import { adminFetch } from "@/lib/admin-api";

export interface AuthActivity {
  providerName: string;
  otpRequestsTotal: number;
  otpRequestFailures: number;
  otpVerificationsTotal: number;
  otpVerificationFailures: number;
  providerSuccessRate: number | null;
  /** Completed Insight registrations. */
  registrationsTotal: number;
  /** Successful logins (existing credential or phone provider OTP). */
  loginsTotal: number;
  /** Successful access/refresh-token rotations. */
  refreshTotal: number;
  /** Whether the Gateway /metrics scrape succeeded. */
  reachable: boolean;
  detail: string;
  checkedAt: string;
}

const COUNTER_NAMES = [
  "auth_phone_provider_requests_total",
  "auth_phone_provider_verifications_total",
  "auth_registrations_total",
  "auth_logins_total",
  "auth_refresh_total",
] as const;

/** Parse a single unlabeled counter value from Prometheus text exposition. */
function parseCounter(body: string, name: string): number {
  // Match `name <value>` at line start, ignoring HELP/TYPE comment lines and
  // any labeled variants (these counters are unlabeled by design).
  const re = new RegExp(`^${name}(?:\\{\\})?\\s+([0-9.eE+-]+)\\s*$`, "m");
  const m = body.match(re);
  if (!m) return 0;
  const v = Number(m[1]);
  return Number.isFinite(v) ? v : 0;
}

function parseProviderCounters(
  body: string,
  name: string,
): { provider: string; total: number; failures: number } {
  const re = new RegExp(`^${name}\\{([^}]*)\\}\\s+([0-9.eE+-]+)\\s*$`, "gm");
  let total = 0;
  let failures = 0;
  let provider = "";
  for (const m of body.matchAll(re)) {
    const labels = m[1] ?? "";
    const value = Number(m[2]);
    if (!Number.isFinite(value)) continue;
    const providerMatch = labels.match(/provider="([^"]+)"/);
    const resultMatch = labels.match(/result="([^"]+)"/);
    const p = providerMatch?.[1] ?? "";
    const result = resultMatch?.[1] ?? "";
    if (!provider && p) provider = p;
    total += value;
    if (result === "failure") failures += value;
  }
  return { provider, total, failures };
}

export async function authActivity(): Promise<AuthActivity> {
  const checkedAt = new Date().toISOString();
  let body = "";
  let reachable = false;
  let detail = "";
  try {
    const r = await adminFetch("/metrics", { timeoutMs: 4000 });
    reachable = r.ok;
    detail = r.ok ? "scraped /metrics" : `metrics HTTP ${r.status}`;
    body = r.ok ? await r.text() : "";
  } catch (e) {
    detail = `unreachable: ${String(e)}`;
  }

  const requests = parseProviderCounters(body, COUNTER_NAMES[0]);
  const verifications = parseProviderCounters(body, COUNTER_NAMES[1]);
  const registrationsTotal = parseCounter(body, COUNTER_NAMES[2]);
  const loginsTotal = parseCounter(body, COUNTER_NAMES[3]);
  const refreshTotal = parseCounter(body, COUNTER_NAMES[4]);

  const providerTotal = requests.total + verifications.total;
  const providerFailures = requests.failures + verifications.failures;
  const providerSuccessRate =
    providerTotal > 0
      ? (providerTotal - providerFailures) / providerTotal
      : null;

  return {
    providerName: requests.provider || verifications.provider || "unknown",
    otpRequestsTotal: requests.total,
    otpRequestFailures: requests.failures,
    otpVerificationsTotal: verifications.total,
    otpVerificationFailures: verifications.failures,
    providerSuccessRate,
    registrationsTotal,
    loginsTotal,
    refreshTotal,
    reachable,
    detail,
    checkedAt,
  };
}
