"use client";

import { useEffect, useState } from "react";
import { BookOpen } from "lucide-react";

import { withBasePath } from "@/lib/base-path";
import { Card, Empty, ErrorBanner, type Row } from "@/components/console/ops-shared";

export function AtlasKnowledgeCenter() {
  const [body, setBody] = useState<Row | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { fetch(withBasePath("/api/v1/data-intelligence/atlas/knowledge"), { cache: "no-store" }).then(async (r) => { const b = await r.json(); if (!r.ok) throw new Error(b.detail ?? `HTTP ${r.status}`); setBody(b); }).catch((e) => setError(e.message)); }, []);
  if (error) return <ErrorBanner>{error}</ErrorBanner>;
  if (!body) return <Empty>Loading Atlas knowledge.</Empty>;
  const sections: [string, unknown][] = [["What patterns exist?", body.patterns], ["What tendencies exist?", body.tendencies], ["What risks exist?", body.risks], ["What signals matter?", body.signals_that_matter], ["What is missing?", body.missing], ["What should improve?", body.should_improve]];
  return <div className="space-y-5"><div><h1 className="flex items-center gap-2 text-xl font-semibold"><BookOpen className="h-5 w-5 text-primary" />Atlas Knowledge Center</h1><p className="text-xs text-muted-foreground">What Atlas knows, lacks and measures across the official historical baseline</p></div><div className="grid gap-3 lg:grid-cols-2">{sections.map(([title, value]) => <Card title={title} key={title}><pre className="max-h-52 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(value, null, 2)}</pre></Card>)}</div><Card title="How Atlas is evolving"><pre className="max-h-72 overflow-auto text-xs">{JSON.stringify(body.evolution, null, 2)}</pre></Card></div>;
}
