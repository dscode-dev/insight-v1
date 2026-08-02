"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Database, FileCheck, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, Empty, ErrorBanner, Pill, type Row } from "@/components/console/ops-shared";
import { withBasePath } from "@/lib/base-path";
import { useT } from "@/lib/i18n/provider";

const CATEGORIES = ["fixtures", "statistics", "odds", "behaviors", "memory", "signals"];
const API = "/api/v1/atlas-datasets";

async function request(path: string, method = "GET", body?: unknown) {
  const response = await fetch(withBasePath(`${API}/${path}`), {
    method, cache: "no-store",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(String(payload.detail ?? payload.error ?? `HTTP ${response.status}`));
  return payload;
}

export function DatasetCenter({ superAdmin }: { superAdmin: boolean }) {
  const t = useT("dataset-center");
  const [datasets, setDatasets] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [category, setCategory] = useState("");
  const [selected, setSelected] = useState<Row | null>(null);
  const [records, setRecords] = useState<Row[]>([]);
  const [recordOffset, setRecordOffset] = useState(0);
  const [recordTotal, setRecordTotal] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [uploadCategory, setUploadCategory] = useState("fixtures");
  const [validation, setValidation] = useState<Row | null>(null);
  const [ingestion, setIngestion] = useState<Row | null>(null);
  const [error, setError] = useState<string | null>(null);
  const limit = 20;

  const refresh = useCallback(async () => {
    try {
      const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
      if (category) query.set("category", category);
      const [response, ingestionResponse] = await Promise.all([
        fetch(withBasePath(`${API}?${query}`), { cache: "no-store" }),
        fetch(withBasePath("/api/v1/data-intelligence/atlas/ingestion"), { cache: "no-store" }),
      ]);
      const body = await response.json();
      if (!response.ok) throw new Error(String(body.detail ?? body.error ?? `HTTP ${response.status}`));
      if (ingestionResponse.ok) setIngestion(await ingestionResponse.json());
      setDatasets(body.items ?? []); setTotal(body.total ?? 0); setError(null);
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("errUnavailable")); }
  }, [category, offset, t]);
  useEffect(() => { refresh(); }, [refresh]);

  const inspect = async (dataset: Row, nextOffset = 0) => {
    const body = await request(`${dataset.dataset_id}/records?limit=25&offset=${nextOffset}`);
    setSelected(dataset); setRecords(body.items ?? []); setRecordTotal(body.total ?? 0); setRecordOffset(nextOffset);
  };
  const fileBody = async () => {
    if (!file) throw new Error(t("errSelectFile"));
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = ""; for (let index = 0; index < bytes.length; index += 0x8000) binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
    const format = file.name.split(".").pop()?.toLowerCase();
    return { name: file.name.replace(/\.[^.]+$/, ""), filename: file.name, format, category: uploadCategory, content_base64: btoa(binary), source_type: "manual" };
  };
  const validate = async () => {
    try { setValidation(await request("validate", "POST", await fileBody())); setError(null); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("errValidation")); }
  };
  const register = async () => {
    try { const result = await request("register", "POST", await fileBody()); setValidation(result); await refresh(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("errRegistration")); }
  };

  return <div className="space-y-5">
    <div><h1 className="flex items-center gap-2 text-xl font-semibold"><Database className="h-5 w-5 text-primary" /> {t("title")}</h1><p className="text-xs text-muted-foreground">{t("subtitle")}</p></div>
    {error ? <ErrorBanner>{error}</ErrorBanner> : null}
    <div className="grid grid-cols-2 gap-2 md:grid-cols-5"><Datum label={t("ing.signals")} value={ingestion?.signals} /><Datum label={t("ing.behaviors")} value={ingestion?.behaviors} /><Datum label={t("ing.vectors")} value={ingestion?.vectors} /><Datum label={t("ing.memories")} value={ingestion?.memories} /><Datum label={t("ing.batches")} value={ingestion?.batches} /></div>
    <Card title={t("filtersTitle")}>
      <select className="input max-w-xs" value={category} onChange={(event) => { setCategory(event.target.value); setOffset(0); }}><option value="">{t("allCategories")}</option>{CATEGORIES.map((value) => <option key={value}>{value}</option>)}</select>
    </Card>
    <Card title={t("registeredDatasets", { count: total })}>
      {datasets.length ? datasets.map((dataset) => <button key={String(dataset.dataset_id)} onClick={() => inspect(dataset)} className="grid w-full grid-cols-[1fr_auto] gap-3 border-b border-border/50 py-3 text-left hover:text-primary">
        <div><p className="font-medium">{String(dataset.name)}</p><p className="font-mono text-xs text-muted-foreground">{String(dataset.checksum)} · {String(dataset.source_type)}</p></div>
        <div className="text-right"><Pill value={String(dataset.status)} /><p className="mt-1 text-xs text-muted-foreground">{t("rowsCategory", { count: String(dataset.row_count), category: String(dataset.category) })}</p></div>
      </button>) : <Empty>{t("noDatasets")}</Empty>}
      <Pager offset={offset} limit={limit} total={total} onChange={setOffset} />
    </Card>
    {selected ? <Card title={t("recordsTitle", { name: String(selected.name) })}>
      <div className="mb-3 grid grid-cols-2 gap-2 text-xs md:grid-cols-4"><Datum label={t("recFormat")} value={selected.format} /><Datum label={t("recValid")} value={selected.valid_rows} /><Datum label={t("recInvalid")} value={selected.invalid_rows} /><Datum label={t("recRegisteredBy")} value={selected.registered_by} /></div>
      {records.map((record) => <details key={String(record.row_number)} className="border-b border-border/50 py-2"><summary className="cursor-pointer text-sm">{t("rowLabel")} {String(record.row_number)} · <Pill value={record.valid ? "valid" : "invalid"} /></summary><pre className="mt-2 overflow-auto rounded bg-background p-2 text-[11px]">{JSON.stringify(record, null, 2)}</pre></details>)}
      <Pager offset={recordOffset} limit={25} total={recordTotal} onChange={(next) => inspect(selected, next)} />
    </Card> : null}
    {superAdmin ? <Card title={t("importTitleSuper")}>
      <p className="mb-3 text-xs text-muted-foreground">{t("importHelp")}</p>
      <div className="mb-3 grid gap-1 text-[11px] text-muted-foreground md:grid-cols-2"><span>fixtures: competition, home_team, away_team, scheduled_at</span><span>statistics: competition, team, observed_at</span><span>odds: competition, teams, observed_at, home/draw/away</span><span>behaviors: competition, behavior, observed_at</span><span>memory: competition, teams, observed_at</span><span>signals: competition, signal_family, observed_at</span></div>
      <div className="grid gap-3 md:grid-cols-3"><input type="file" accept=".csv,.json,.ndjson,.parquet" onChange={(event) => { setFile(event.target.files?.[0] ?? null); setValidation(null); }} /><select className="input" value={uploadCategory} onChange={(event) => setUploadCategory(event.target.value)}>{CATEGORIES.map((value) => <option key={value}>{value}</option>)}</select><div className="flex gap-2"><Button variant="outline" onClick={validate} disabled={!file}><FileCheck className="h-4 w-4" />{t("validateBtn")}</Button><Button onClick={register} disabled={!file || validation?.status !== "valid"}><Upload className="h-4 w-4" />{t("registerBtn")}</Button></div></div>
      {validation ? <div className="mt-4"><div className="grid grid-cols-2 gap-2 md:grid-cols-5"><Datum label={t("valStatus")} value={validation.status} /><Datum label={t("valRows")} value={validation.rows} /><Datum label={t("valValid")} value={validation.valid_rows} /><Datum label={t("valInvalid")} value={validation.invalid_rows} /><Datum label={t("valChecksum")} value={validation.checksum} /></div><details className="mt-3"><summary className="cursor-pointer text-xs text-primary">{t("validationDetails")}</summary><pre className="mt-2 max-h-80 overflow-auto rounded bg-background p-3 text-[11px]">{JSON.stringify(validation, null, 2)}</pre></details></div> : null}
    </Card> : <Card title={t("importTitle")}><Empty>{t("superRequired")}</Empty></Card>}
  </div>;
}

function Pager({ offset, limit, total, onChange }: { offset: number; limit: number; total: number; onChange: (value: number) => void }) {
  const tc = useT("common");
  return <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground"><span>{offset + 1}–{Math.min(total, offset + limit)} {tc("of")} {total}</span><div className="flex gap-1"><Button size="sm" variant="outline" disabled={!offset} onClick={() => onChange(Math.max(0, offset - limit))}><ChevronLeft className="h-3.5 w-3.5" /></Button><Button size="sm" variant="outline" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}><ChevronRight className="h-3.5 w-3.5" /></Button></div></div>;
}
function Datum({ label, value }: { label: string; value: unknown }) { return <div className="rounded border border-border p-2"><p className="text-[10px] uppercase text-muted-foreground">{label}</p><p className="mt-1 break-all font-mono text-xs">{String(value ?? "—")}</p></div>; }
