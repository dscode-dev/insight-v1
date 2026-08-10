"use client";

// Lembretes operacionais — prazos que só aparecem quando já quebraram.
//
// O que motivou a tela: o par mTLS entre Gateway e Social vence em
// novembro de 2028. Um certificado vencido não degrada — o gRPC para, a
// API social inteira cai junto, e a mensagem que o operador vê não fala
// em data nenhuma.
//
// DUAS ESPÉCIES, e a diferença é o desenho todo:
//
//   DERIVADO — o prazo é propriedade de um artefato real (o `notAfter` de
//   um certificado). Ninguém digita: quem detém o artefato REPORTA, e o
//   lembrete é tão velho quanto o último relato.
//
//   DECLARADO — o prazo é política ("rotacionar a cada 90 dias"). Não há
//   artefato para ler; o operador declara o período e registra quando fez.
//
// Por isso não existe campo "vence em" para os derivados. Data digitada é
// data que envelhece: rotacionado o certificado, o campo continua
// apontando para um prazo que deixou de ser verdade no instante em que a
// coisa que ele descreve mudou.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BellRing,
  CalendarClock,
  CheckCircle2,
  HelpCircle,
  Loader2,
  Plus,
  Volume2,
  VolumeX,
} from "lucide-react";

import { withBasePath } from "@/lib/base-path";
import { Card, Empty, ErrorBanner, PageHeader } from "@/components/console/ops-shared";
import { cn } from "@/lib/utils";

const API = "/api/v1/reminders";

type Status = "overdue" | "due" | "unknown" | "muted" | "ok";

interface Reminder {
  id: string;
  slug: string;
  title: string;
  impact: string;
  kind: "derived" | "declared";
  dueAt: string | null;
  status: Status;
  daysRemaining: number | null;
  leadDays: number;
  periodDays: number | null;
  lastDoneAt: string | null;
  observedAt: string | null;
  observedDetail: string | null;
  mutedUntil: string | null;
  notes: string | null;
  updatedBy: string | null;
}

const STATUS_LABEL: Record<Status, string> = {
  overdue: "vencido",
  due: "a vencer",
  unknown: "sem informação",
  muted: "silenciado",
  ok: "em dia",
};

const STATUS_TONE: Record<Status, string> = {
  overdue: "border-red-500/40 bg-red-500/[0.07] text-red-400",
  due: "border-amber-500/40 bg-amber-500/[0.07] text-amber-400",
  // Cinza, e não verde: "sem informação" não é "está tudo bem". É
  // exatamente o estado que esta tela existe para não deixar passar.
  unknown: "border-border bg-muted/40 text-muted-foreground",
  muted: "border-border bg-muted/40 text-muted-foreground",
  ok: "border-emerald-500/40 bg-emerald-500/[0.07] text-emerald-400",
};

// A ordem em que um operador precisa ver. O backend já devolve por
// vencimento; isto agrupa antes disso, para que "sem informação" não
// afunde no fim da lista por não ter data.
const ORDER: Status[] = ["overdue", "due", "unknown", "ok", "muted"];

function dateLabel(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleDateString("pt-BR", {
        day: "2-digit",
        month: "short",
        year: "numeric",
      });
}

/** "faltam 47 dias" / "venceu há 3 dias" / "vence hoje". */
function remainingLabel(days: number | null): string {
  if (days === null) return "sem prazo conhecido";
  if (days === 0) return "vence hoje";
  if (days < 0) {
    const late = Math.abs(days);
    return `venceu há ${late} ${late === 1 ? "dia" : "dias"}`;
  }
  return `faltam ${days} ${days === 1 ? "dia" : "dias"}`;
}

async function request(path: string, body?: unknown): Promise<unknown> {
  const response = await fetch(withBasePath(`${API}${path}`), {
    method: body === undefined ? "GET" : "POST",
    cache: "no-store",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = (await response.json().catch(() => ({}))) as {
    detail?: unknown;
    message?: unknown;
  };
  if (!response.ok) {
    const detail = payload.message ?? payload.detail ?? `HTTP ${response.status}`;
    throw new Error(String(detail));
  }
  return payload;
}

export function RemindersCenter() {
  const [reminders, setReminders] = useState<Reminder[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      const payload = (await request("")) as { reminders?: Reminder[] };
      setReminders(payload.reminders ?? []);
      setError(null);
      setUpdated(new Date());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "indisponível");
      setReminders((current) => current ?? []);
    }
  }, []);

  // Sem polling. Um prazo se move na escala de dias — reconsultar a cada
  // sete segundos gastaria uma conexão para reencontrar exatamente o mesmo
  // número.
  useEffect(() => {
    void load();
  }, [load]);

  const act = useCallback(
    async (slug: string, action: string, body: unknown) => {
      setBusy(`${slug}:${action}`);
      try {
        await request(`/${slug}/${action}`, body);
        await load();
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "falhou");
      } finally {
        setBusy(null);
      }
    },
    [load],
  );

  const grouped = useMemo(() => {
    const buckets = new Map<Status, Reminder[]>();
    for (const status of ORDER) buckets.set(status, []);
    for (const reminder of reminders ?? []) {
      buckets.get(reminder.status)?.push(reminder);
    }
    return buckets;
  }, [reminders]);

  const counts = useMemo(() => {
    const out: Record<Status, number> = {
      overdue: 0,
      due: 0,
      unknown: 0,
      muted: 0,
      ok: 0,
    };
    for (const reminder of reminders ?? []) out[reminder.status] += 1;
    return out;
  }, [reminders]);

  return (
    <div className="space-y-5">
      <PageHeader
        icon={BellRing}
        title="Lembretes operacionais"
        subtitle="Prazos de certificados e rotações de credencial · atualizado sob demanda"
        updated={updated}
        onRefresh={() => void load()}
      />

      {error && <ErrorBanner>{error}</ErrorBanner>}

      <div className="flex flex-wrap gap-2">
        {ORDER.map((status) => (
          <span
            key={status}
            className={cn(
              "rounded-lg border px-3 py-1.5 text-xs font-medium",
              counts[status] === 0
                ? "border-border bg-card/60 text-muted-foreground"
                : STATUS_TONE[status],
            )}
          >
            {counts[status]} {STATUS_LABEL[status]}
          </span>
        ))}
        <button
          onClick={() => setCreating((open) => !open)}
          className="ix-transition ml-auto inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium hover:bg-accent"
        >
          <Plus className="h-3.5 w-3.5" /> Nova rotina
        </button>
      </div>

      {creating && (
        <CreateDeclared
          onDone={async () => {
            setCreating(false);
            await load();
          }}
          onError={setError}
        />
      )}

      {reminders !== null && reminders.length === 0 && (
        <Empty>
          Nenhum lembrete cadastrado. A migração semeia os prazos reais do
          ambiente (par mTLS e rotação dos tokens) — uma lista vazia aqui
          significa que ela não foi aplicada.
        </Empty>
      )}

      {ORDER.map((status) => {
        const items = grouped.get(status) ?? [];
        if (items.length === 0) return null;
        return (
          <section key={status} className="space-y-2">
            <h2 className="text-[10px] uppercase tracking-wider text-muted-foreground">
              {STATUS_LABEL[status]}
            </h2>
            <div className="grid gap-3 lg:grid-cols-2">
              {items.map((reminder) => (
                <ReminderCard
                  key={reminder.id}
                  reminder={reminder}
                  busy={busy}
                  onAct={act}
                />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function ReminderCard({
  reminder,
  busy,
  onAct,
}: {
  reminder: Reminder;
  busy: string | null;
  onAct: (slug: string, action: string, body: unknown) => Promise<void>;
}) {
  const [muting, setMuting] = useState(false);
  const [until, setUntil] = useState("");
  const working = busy?.startsWith(`${reminder.slug}:`) ?? false;

  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold">{reminder.title}</p>
          <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
            {reminder.slug}
          </p>
        </div>
        <span
          className={cn(
            "shrink-0 rounded border px-1.5 py-0.5 text-[11px]",
            STATUS_TONE[reminder.status],
          )}
        >
          {STATUS_LABEL[reminder.status]}
        </span>
      </div>

      {/* O impacto vem antes da data. Um lembrete cuja consequência não
          está escrita é adiado por quem estiver de plantão. */}
      <p className="mt-2 flex gap-1.5 text-xs text-muted-foreground">
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>{reminder.impact}</span>
      </p>

      <div className="mt-3 space-y-1 text-xs">
        <p className="flex items-center gap-1.5">
          <CalendarClock className="h-3.5 w-3.5 text-muted-foreground" />
          <span>
            {dateLabel(reminder.dueAt)} · {remainingLabel(reminder.daysRemaining)}
          </span>
        </p>

        {reminder.kind === "derived" ? (
          <p className="flex items-start gap-1.5 text-muted-foreground">
            <HelpCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              {reminder.observedAt
                ? `Observado em ${dateLabel(reminder.observedAt)}${
                    reminder.observedDetail ? ` — ${reminder.observedDetail}` : ""
                  }`
                : "Ninguém reportou este artefato ainda. O prazo existe de todo " +
                  "jeito — só não sabemos qual. Reporte com " +
                  "`node dist/cli.js reminders:report`."}
            </span>
          </p>
        ) : (
          <p className="text-muted-foreground">
            A cada {reminder.periodDays} dias · última vez{" "}
            {reminder.lastDoneAt ? dateLabel(reminder.lastDoneAt) : "nunca"}
            {reminder.updatedBy ? ` (${reminder.updatedBy})` : ""}
          </p>
        )}

        {reminder.mutedUntil && (
          <p className="text-muted-foreground">
            Silenciado até {dateLabel(reminder.mutedUntil)}
          </p>
        )}
        {reminder.notes && (
          <p className="whitespace-pre-line text-muted-foreground">{reminder.notes}</p>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {reminder.kind === "declared" && (
          <button
            disabled={working}
            onClick={() => void onAct(reminder.slug, "done", {})}
            className="ix-transition inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-50"
          >
            {working ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <CheckCircle2 className="h-3.5 w-3.5" />
            )}
            Marcar como feito hoje
          </button>
        )}
        {reminder.status === "muted" ? (
          // Voltar a ouvir passa pelo mesmo caminho auditado de silenciar.
          // Sem isto, silenciar seria porta de uma via só: a API recusa
          // data no passado, então nada desfaria o silêncio.
          <button
            disabled={working}
            onClick={() => void onAct(reminder.slug, "mute", { until: null })}
            className="ix-transition inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-50"
          >
            <Volume2 className="h-3.5 w-3.5" /> Voltar a mostrar
          </button>
        ) : (
          <button
            disabled={working}
            onClick={() => setMuting((open) => !open)}
            className="ix-transition inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-50"
          >
            <VolumeX className="h-3.5 w-3.5" /> Silenciar
          </button>
        )}
      </div>

      {muting && (
        <div className="mt-2 space-y-2 rounded-lg border border-border bg-background/40 p-3">
          {/* Silenciar tem data-limite obrigatória. Um mute indefinido é
              uma exclusão que ainda ocupa uma linha, e o prazo não deixa
              de existir por ninguém estar olhando. */}
          <label className="block text-xs text-muted-foreground">
            Silenciar até (a data é obrigatória — não existe silêncio
            indefinido)
            <input
              type="date"
              value={until}
              onChange={(event) => setUntil(event.target.value)}
              className="mt-1 w-full rounded-lg border border-border bg-card px-2 py-1.5 text-xs"
            />
          </label>
          <button
            disabled={!until || working}
            onClick={() => {
              // meio-dia UTC: uma data pura viraria meia-noite local e, a
              // oeste de Greenwich, o silêncio acabaria no dia anterior.
              void onAct(reminder.slug, "mute", {
                until: `${until}T12:00:00Z`,
              }).then(() => setMuting(false));
            }}
            className="ix-transition inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-50"
          >
            Confirmar
          </button>
        </div>
      )}
    </Card>
  );
}

function CreateDeclared({
  onDone,
  onError,
}: {
  onDone: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const [form, setForm] = useState({
    slug: "",
    title: "",
    impact: "",
    periodDays: "90",
    leadDays: "7",
    notes: "",
  });
  const [saving, setSaving] = useState(false);

  const set = (field: keyof typeof form) => (value: string) =>
    setForm((current) => ({ ...current, [field]: value }));

  const submit = async () => {
    setSaving(true);
    try {
      await request("", {
        slug: form.slug.trim(),
        title: form.title.trim(),
        impact: form.impact.trim(),
        periodDays: Number(form.periodDays),
        leadDays: Number(form.leadDays),
        notes: form.notes.trim() || undefined,
      });
      await onDone();
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : "não foi possível criar");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title="Nova rotina">
      {/* Só rotinas. Um lembrete DERIVADO criado por aqui não teria nada
          reportando nele e ficaria "sem informação" para sempre — o
          artefato precisa ganhar um reporter antes, e isso é código. */}
      <p className="mb-3 text-xs text-muted-foreground">
        Aqui só se cadastra política — "a cada N dias". Prazo de artefato
        (validade de certificado, por exemplo) não se digita: quem detém o
        arquivo reporta, para o lembrete não sobreviver à coisa que descreve.
      </p>
      <div className="grid gap-2 md:grid-cols-2">
        <Field label="Identificador (minúsculas e hífens)" value={form.slug} onChange={set("slug")} placeholder="rotacionar-token-x" />
        <Field label="Título" value={form.title} onChange={set("title")} placeholder="Rotacionar o token X" />
        <Field
          label="O que quebra se passar do prazo"
          value={form.impact}
          onChange={set("impact")}
          placeholder="Descreva a consequência, não a tarefa"
        />
        <Field label="Período (dias)" value={form.periodDays} onChange={set("periodDays")} type="number" />
        <Field label="Avisar com quantos dias de antecedência" value={form.leadDays} onChange={set("leadDays")} type="number" />
        <Field label="Observações" value={form.notes} onChange={set("notes")} placeholder="Onde fica, o que precisa trocar junto" />
      </div>
      <button
        disabled={saving || !form.slug || !form.title || !form.impact}
        onClick={() => void submit()}
        className="ix-transition mt-3 inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-50"
      >
        {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
        Cadastrar
      </button>
    </Card>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <label className="block text-xs text-muted-foreground">
      {label}
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 w-full rounded-lg border border-border bg-card px-2 py-1.5 text-xs text-foreground"
      />
    </label>
  );
}
