"use client";

import { useEffect, useState } from "react";
import { Brain, Search } from "lucide-react";

import { withBasePath } from "@/lib/base-path";
import { Button } from "@/components/ui/button";
import { Card, Empty, ErrorBanner, Pill, type Row } from "@/components/console/ops-shared";

const TYPES = ["competition", "team", "season", "dataset", "trend"] as const;

export function AtlasIntelligenceWorkspace() {
  const [type, setType] = useState<(typeof TYPES)[number]>("competition");
  const [query, setQuery] = useState("brasileirao_serie_a");
  const [report, setReport] = useState<Row | null>(null);
  const [comparison, setComparison] = useState<Row | null>(null);
  const [error, setError] = useState<string | null>(null);
  const analyze = async () => {
    try {
      const r = await fetch(withBasePath("/api/v1/data-intelligence/atlas/analyze"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ analysis_type: type, query }) });
      const body = await r.json(); if (!r.ok) throw new Error(body.detail ?? `HTTP ${r.status}`); setReport(body); setError(null);
    } catch (e) { setError(e instanceof Error ? e.message : "unreachable"); }
  };
  useEffect(() => { fetch(withBasePath("/api/v1/data-intelligence/atlas/comparison"), { cache: "no-store" }).then((r) => r.json()).then(setComparison).catch(() => undefined); }, []);
  return <div className="space-y-5">
    <div><h1 className="flex items-center gap-2 text-xl font-semibold"><Brain className="h-5 w-5 text-primary" />Atlas Intelligence Workspace</h1><p className="text-xs text-muted-foreground">Deterministic patterns, tendencies, regimes and uncertainty · no predictions · no LLM</p></div>
    {error ? <ErrorBanner>{error}</ErrorBanner> : null}
    <Card title="Analysis query"><div className="flex flex-wrap gap-2"><select className="input max-w-44" value={type} onChange={(e) => setType(e.target.value as typeof type)}>{TYPES.map((t) => <option key={t}>{t}</option>)}</select><input className="input min-w-64 flex-1" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Brasileirão 2024, Flamengo, mld5, draw tendencies…" /><Button onClick={analyze}><Search className="h-4 w-4" />Analyze</Button></div></Card>
    {report ? <IntelligenceReport report={report} /> : <Empty>Choose an analysis scope. Atlas will only describe measured historical evidence.</Empty>}
    <ModelComparison body={comparison} />
  </div>;
}

function IntelligenceReport({ report }: { report: Row }) {
  const context = (report.context as Row) ?? {}; const confidence = (report.confidence as Row) ?? {};
  return <div className="space-y-3">
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4"><M label="sample size" value={context.sample_size} /><M label="confidence" value={confidence.confidence} /><M label="uncertainty" value={confidence.uncertainty} /><M label="calibration ECE" value={confidence.calibration} /></div>
    <div className="grid gap-3 lg:grid-cols-2"><ListCard title="Tendencies" values={(report.tendencies as Row[])?.map((v) => `${v.tendency} (${v.delta})`) ?? []} /><ListCard title="Regimes" values={(report.regimes as string[]) ?? []} /><ListCard title="Signals" values={(report.signals as Row[])?.map((v) => `${v.signal}: ${v.strength ?? "unavailable"} — ${v.evidence}`) ?? []} /><ListCard title="Risks" values={(report.risks as string[]) ?? []} /><ListCard title="Missing information" values={(report.missing_information as string[]) ?? []} /><ListCard title="Data improvements" values={(report.improvement_suggestions as string[]) ?? []} /></div>
    <Card title="Coverage context"><pre className="max-h-64 overflow-auto text-xs">{JSON.stringify({ sources: context.source_coverage, competitions: context.competition_coverage, seasons: context.season_coverage }, null, 2)}</pre></Card>
  </div>;
}

function ModelComparison({ body }: { body: Row | null }) {
  const models = (body?.models as Row) ?? {};
  return <Card title="Atlas evolution — candidate comparison"><div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead className="text-muted-foreground"><tr><th>Version</th><th>Status</th><th>Holdout</th><th>Balanced accuracy</th><th>Uncertainty</th><th>ECE</th><th>Draw recall</th></tr></thead><tbody>{Object.entries(models).map(([name, raw]) => { const m = raw as Row; return <tr className="border-t border-border" key={name}><td className="font-mono">{name}</td><td><Pill value={String(m.status)} /></td><td>{String(m.holdout ?? "—")}</td><td>{String(m.balanced_accuracy ?? "—")}</td><td>{String(m.uncertainty ?? "—")}</td><td>{String(m.ece ?? "—")}</td><td>{String(m.draw_recall ?? "—")}</td></tr>; })}</tbody></table></div></Card>;
}

function ListCard({ title, values }: { title: string; values: string[] }) { return <Card title={title}>{values.length ? <ul className="space-y-1 text-sm">{values.map((v, i) => <li key={`${v}-${i}`}>• {v}</li>)}</ul> : <Empty>No measured item.</Empty>}</Card>; }
function M({ label, value }: { label: string; value: unknown }) { return <div className="rounded border border-border bg-card/60 p-3"><p className="text-[10px] uppercase text-muted-foreground">{label}</p><p className="mt-1 font-mono text-lg">{String(value ?? "—")}</p></div>; }
