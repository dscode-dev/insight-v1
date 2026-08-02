"use client";

// /login — Insight Operations Center (Pre-ML-C redesign).
// Username/email + password (no phone, no OTP). Premium split-screen:
// brand panel + auth card. Dark-first, enterprise SaaS feel.

import Image from "next/image";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { Lock, User, ArrowRight, ShieldCheck, Activity, Boxes } from "lucide-react";

import { InsightWordmark } from "@/components/brand/logo";
import { withBasePath, withoutBasePath } from "@/lib/base-path";

export default function LoginPage() {
  return (
    <Suspense>
      <LoginExperience />
    </Suspense>
  );
}

function LoginExperience() {
  const router = useRouter();
  const params = useSearchParams();
  const requestedNext = params.get("next") ?? "/operations";
  const next = normalizeNextPath(requestedNext);

  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await fetch(withBasePath("/api/auth/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identifier, password }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(translateError(body.error ?? "auth_failed"));
        return;
      }
      router.replace(next);
      router.refresh();
    } catch {
      setError("Network error — could not reach the authentication service.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      {/* Brand panel */}
      <aside className="relative hidden overflow-hidden border-r border-white/5 bg-[#070b14] lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div
          className="pointer-events-none absolute inset-0 opacity-70"
          style={{
            background:
              "radial-gradient(60% 50% at 20% 15%, rgba(56,121,255,0.18), transparent 60%)," +
              "radial-gradient(45% 40% at 85% 80%, rgba(16,185,129,0.12), transparent 60%)",
          }}
        />
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.04]"
          style={{
            backgroundImage:
              "linear-gradient(to right, #fff 1px, transparent 1px), linear-gradient(to bottom, #fff 1px, transparent 1px)",
            backgroundSize: "44px 44px",
          }}
        />
        <div className="relative flex items-center gap-2.5">
          <Image src={withBasePath("/insight-logo.png")} alt="Insight" width={34} height={34}
            priority className="rounded-[22%] ring-1 ring-inset ring-white/10" />
          <InsightWordmark className="text-base text-white" />
        </div>

        <div className="relative max-w-md">
          <h1 className="text-4xl font-semibold leading-tight tracking-tight text-white">
            Insight<br />Operations Center
          </h1>
          <p className="mt-4 text-sm leading-relaxed text-slate-400">
            The control plane for the Insight platform — historical collection,
            AI-orchestrated data quality, runtime observability and operator
            controls, in one place.
          </p>
          <ul className="mt-8 space-y-3 text-sm text-slate-300">
            <Feature icon={<Activity className="h-4 w-4 text-blue-400" />} text="Live runtime telemetry & job control" />
            <Feature icon={<Boxes className="h-4 w-4 text-emerald-400" />} text="Dataset quality, entity resolution & review" />
            <Feature icon={<ShieldCheck className="h-4 w-4 text-violet-400" />} text="Audited, role-based operator actions" />
          </ul>
        </div>

        <div className="relative flex items-center gap-2 text-xs text-slate-500">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
          All systems operational
        </div>
      </aside>

      {/* Auth card */}
      <main className="flex items-center justify-center bg-background px-6 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <div className="flex items-center gap-2">
              <Image src={withBasePath("/insight-logo.png")} alt="Insight" width={30} height={30}
                priority className="rounded-[22%] ring-1 ring-inset ring-white/10" />
              <InsightWordmark className="text-base" />
            </div>
          </div>

          <div className="mb-7">
            <h2 className="text-xl font-semibold tracking-tight">Sign in</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Operator access to the Insight Operations Center.
            </p>
          </div>

          <form onSubmit={submit} className="space-y-4">
            <Field
              icon={<User className="h-4 w-4" />}
              label="Username or email"
              type="text"
              autoComplete="username"
              value={identifier}
              onChange={setIdentifier}
              placeholder="superadmin"
              autoFocus
            />
            <Field
              icon={<Lock className="h-4 w-4" />}
              label="Password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={setPassword}
              placeholder="••••••••••••"
            />

            {error ? (
              <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
                {error}
              </div>
            ) : null}

            <button
              type="submit"
              disabled={submitting || !identifier || !password}
              className="group flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? "Signing in…" : "Sign in"}
              {!submitting && <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />}
            </button>
          </form>

          <p className="mt-8 text-center text-[11px] leading-relaxed text-muted-foreground">
            Authorized operators only. All sessions are audited.
          </p>
        </div>
      </main>
    </div>
  );
}

function normalizeNextPath(value: string): string {
  if (!value.startsWith("/") || value.startsWith("//")) return "/operations";
  let appPath = withoutBasePath(value);
  while (withoutBasePath(appPath) !== appPath) {
    appPath = withoutBasePath(appPath);
  }
  if (!appPath.startsWith("/") || appPath.startsWith("//")) return "/operations";
  return appPath;
}

function Feature({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <li className="flex items-center gap-3">
      <span className="flex h-7 w-7 items-center justify-center rounded-md bg-white/5 ring-1 ring-inset ring-white/10">
        {icon}
      </span>
      {text}
    </li>
  );
}

function Field({ icon, label, type, value, onChange, placeholder, autoComplete, autoFocus }: {
  icon: React.ReactNode; label: string; type: string; value: string;
  onChange: (v: string) => void; placeholder?: string; autoComplete?: string; autoFocus?: boolean;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-muted-foreground">{label}</span>
      <span className="relative block">
        <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground">
          {icon}
        </span>
        <input
          type={type}
          value={value}
          autoComplete={autoComplete}
          autoFocus={autoFocus}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="w-full rounded-lg border border-border bg-card py-2.5 pl-9 pr-3 text-sm text-foreground shadow-sm outline-none transition-colors placeholder:text-muted-foreground/50 focus:border-primary/60 focus:ring-2 focus:ring-primary/20"
        />
      </span>
    </label>
  );
}

function translateError(code: string): string {
  switch (code) {
    case "invalid_credentials":
      return "Incorrect username/email or password.";
    case "console_access_required":
      return "This account is valid but lacks operations-center access.";
    case "auth_unavailable":
      return "Authentication service unavailable. Try again shortly.";
    case "identifier_required":
    case "password_required":
      return "Enter both your username/email and password.";
    default:
      return "Sign-in failed. Please try again.";
  }
}
