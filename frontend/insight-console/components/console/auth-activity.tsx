"use client";

// Authentication activity (Auth-A Part 11) — read-only view of the LIVE auth_*
// counters from the Gateway. Polls /api/v1/auth/activity. No mocks, no actions:
// the Console observes the provider-phone → Insight-session funnel.

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ShieldCheck, RefreshCw, Smartphone, UserPlus, LogIn, RotateCw, XCircle,
} from "lucide-react";

import { withBasePath } from "@/lib/base-path";
import { cn } from "@/lib/utils";

type Activity = {
  providerName: string;
  otpRequestsTotal: number;
  otpRequestFailures: number;
  otpVerificationsTotal: number;
  otpVerificationFailures: number;
  providerSuccessRate: number | null;
  registrationsTotal: number;
  loginsTotal: number;
  refreshTotal: number;
  reachable: boolean;
  detail: string;
  checkedAt: string;
};

function fmt(n: number): string {
  return new Intl.NumberFormat("en-US").format(n);
}

export function AuthActivity() {
  const [data, setData] = useState<Activity | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [loading, setLoading] = useState(true);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(withBasePath("/api/v1/auth/activity"), { cache: "no-store" });
      if (r.ok) {
        setData(await r.json());
        setUpdated(new Date());
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    timer.current = setInterval(refresh, 10000);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [refresh]);

  const reachable = data?.reachable ?? false;
  const successPct =
    data?.providerSuccessRate != null
      ? `${(data.providerSuccessRate * 100).toFixed(1)}%`
      : "—";

  const cards: { label: string; value: string; sub: string; Icon: typeof LogIn }[] =
    data
      ? [
          {
            label: "Provider",
            value: data.providerName,
            sub: `${successPct} success`,
            Icon: Smartphone,
          },
          {
            label: "OTP requests",
            value: fmt(data.otpRequestsTotal),
            sub: `${fmt(data.otpRequestFailures)} failures`,
            Icon: Smartphone,
          },
          {
            label: "OTP verifications",
            value: fmt(data.otpVerificationsTotal),
            sub: `${fmt(data.otpVerificationFailures)} failures`,
            Icon: XCircle,
          },
          {
            label: "Logins",
            value: fmt(data.loginsTotal),
            sub: "existing credentials",
            Icon: LogIn,
          },
          {
            label: "Registrations",
            value: fmt(data.registrationsTotal),
            sub: "new Insight identities",
            Icon: UserPlus,
          },
          {
            label: "Token refreshes",
            value: fmt(data.refreshTotal),
            sub: "rotations (server-side)",
            Icon: RotateCw,
          },
        ]
      : [];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
            <ShieldCheck className="h-5 w-5 text-primary" /> Authentication
          </h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Gateway phone provider → Insight session ·{" "}
            <span className={reachable ? "text-emerald-400" : "text-amber-400"}>
              {reachable ? "Gateway metrics live" : "Gateway metrics unreachable"}
            </span>
            {updated ? (
              <span className="ml-2">updated {updated.toLocaleTimeString()}</span>
            ) : null}
          </p>
        </div>
        <button
          onClick={refresh}
          className="ix-transition inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium hover:bg-accent"
        >
          <RefreshCw className="h-3.5 w-3.5" /> Refresh
        </button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {(loading && !data ? Array.from({ length: 6 }) : cards).map((c, i) => {
          const card = c as (typeof cards)[number] | undefined;
          if (!card) {
            return (
              <div
                key={i}
                className="h-28 animate-pulse rounded-xl border border-border bg-card/60"
              />
            );
          }
          const Icon = card.Icon;
          return (
            <div
              key={card.label}
              className="ix-transition rounded-xl border border-border bg-card/60 p-4 hover:border-border/80"
            >
              <div className="flex items-center gap-2.5">
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-secondary ring-1 ring-inset ring-border">
                  <Icon className="h-4 w-4 text-muted-foreground" />
                </span>
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  {card.label}
                </p>
              </div>
              <p className="mt-3 font-mono text-2xl font-semibold tabular-nums text-foreground">
                {card.value}
              </p>
              <p className="mt-1 text-[11px] text-muted-foreground">{card.sub}</p>
            </div>
          );
        })}
      </div>

      <p className="text-[11px] text-muted-foreground">
        Read-only. Counters are scraped live from the Gateway&apos;s{" "}
        <span className="font-mono">/metrics</span> (
        <span className="font-mono">auth_phone_provider_requests_total</span>,{" "}
        <span className="font-mono">auth_phone_provider_verifications_total</span>,{" "}
        <span className="font-mono">auth_logins_total</span>,{" "}
        <span className="font-mono">auth_registrations_total</span>,{" "}
        <span className="font-mono">auth_refresh_total</span>). The provider only
        verifies phone ownership; identity, sessions and refresh are Insight-owned.
        {data && !reachable ? (
          <span className="ml-1 text-amber-400">({data.detail})</span>
        ) : null}
      </p>
    </div>
  );
}
