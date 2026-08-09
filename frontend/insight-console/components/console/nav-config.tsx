// Console navigation config (Console-X). Grouped into operator-meaningful
// sections. Shared by the server layout (permission filtering) and the client
// SidebarNav (rendering). Icons are lucide components.

import {
  Activity, AlertOctagon, ServerCog,
  Newspaper, BarChart3,
  Brain, BookOpen, Database, GitBranch, Radio, Server, Ticket,
  ScrollText, ShieldCheck, ShieldAlert, ClipboardList,
  Users, UserCog, KeyRound,
  Gauge, Bot, FileText,
  MessageSquare, Boxes, Zap, Flag, Gavel,
} from "lucide-react";

import type { Permission } from "@/types/auth";

export type NavItem = {
  href: string;
  /** i18n key (navigation: `item.<key>`). English in `label` is the fallback. */
  key: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  permission: Permission;
};

export type NavGroup = { key: string; label: string; items: NavItem[] };

export const NAV_GROUPS: NavGroup[] = [
  // ORGANIZADO POR PLANO, seguindo insight-context.md v2.0. O menu
  // antigo misturava planos e listava 33 telas, das quais 14 não podiam
  // funcionar — o operador não tinha como saber quais.
  //
  // A regra aplicada: um item só entra aqui se a API que ele consome
  // responde com dado real contra a stack. O que foi retirado está
  // listado em REMOVED_FROM_NAV, no fim do arquivo, com o motivo e o
  // que o traria de volta.

  {
    key: "overview",
    label: "Visão geral",
    items: [
      { href: "/operations", key: "operations", label: "Painel", icon: Gauge, permission: "console.access" },
    ],
  },

  // ---- Plano de Inteligência: onde está o valor da plataforma ----
  {
    key: "data",
    label: "Dados (Explorer)",
    items: [
      { href: "/data-intelligence/pipelines", key: "mission-center", label: "Pipelines", icon: GitBranch, permission: "console.access" },
      { href: "/data-intelligence/jobs", key: "explorer-jobs", label: "Coletas", icon: Activity, permission: "config.read" },
      { href: "/data-intelligence/curation", key: "curation", label: "Curadoria", icon: ClipboardList, permission: "config.read" },
      { href: "/data-intelligence/quality", key: "explorer-quality", label: "Qualidade", icon: BarChart3, permission: "config.read" },
      { href: "/data-intelligence/sources", key: "sources", label: "Fontes", icon: Server, permission: "console.access" },
      { href: "/data-intelligence/signal-sources", key: "signal-sources", label: "Fontes de sinal", icon: Radio, permission: "console.access" },
      { href: "/data-intelligence/tickets", key: "tickets", label: "Tickets", icon: Ticket, permission: "console.access" },
      { href: "/data-intelligence/runtime", key: "explorer-runtime", label: "Runtime", icon: ServerCog, permission: "config.read" },
    ],
  },
  {
    key: "intelligence",
    label: "Inteligência (Atlas)",
    items: [
      // Primeiro na lista de propósito: é onde a aprovação humana que o
      // ATLAS_V1_FROZEN.md exige acontece.
      { href: "/atlas/quality-gate", key: "atlas-quality-gate", label: "Quality Gate", icon: ShieldCheck, permission: "config.read" },
      { href: "/atlas/intelligence", key: "atlas-intelligence", label: "Inteligência", icon: Brain, permission: "console.access" },
      { href: "/atlas/knowledge", key: "atlas-knowledge", label: "Conhecimento", icon: BookOpen, permission: "console.access" },
      { href: "/data-intelligence/datasets", key: "dataset-center", label: "Datasets", icon: Database, permission: "console.access" },
    ],
  },

  {
    key: "communication",
    label: "Comunicação (Nexus)",
    items: [
      // Agentes vem primeiro: e onde estao as RESTRICOES de cada persona,
      // o contrato negativo equivalente aos guardrails do Atlas.
      { href: "/nexus/agents", key: "nexus-agents", label: "Agentes", icon: Bot, permission: "console.access" },
      { href: "/nexus/publications", key: "nexus-publications", label: "Publicações", icon: Newspaper, permission: "console.access" },
    ],
  },

  // ---- Plano de Produto: administrado A PARTIR daqui ----
  //
  // O insight-context.md v2.0 diz que o Console tem "controle e gerencia
  // total dos modulos contidos no insight-social". Estas telas voltaram
  // quando o caminho passou a existir: Console -> Control Plane -> Social,
  // direto, em vez de atravessar o gateway publico (que o mesmo documento
  // exclui de Administracao e Console).
  //
  // Elas dependem de configuracao que vive fora do codigo — o ingress do
  // Social e o SOCIAL_OPS_TOKEN nos dois lados. Sem isso respondem
  // "Social read plane unavailable", que e um estado honesto e nomeado,
  // nao uma tela em branco. Ver docs/adr/0001-social-administration-path.md.
  {
    key: "social",
    label: "Rede social (Social)",
    items: [
      { href: "/social", key: "social", label: "Visao geral", icon: MessageSquare, permission: "feed.read" },
      { href: "/social/users", key: "social-users", label: "Usuarios", icon: Users, permission: "user.read" },
      { href: "/social/agents", key: "social-agents", label: "Agentes", icon: Bot, permission: "feed.read" },
      { href: "/social/posts", key: "social-posts", label: "Posts", icon: FileText, permission: "feed.read" },
      { href: "/social/comments", key: "social-comments", label: "Comentarios", icon: MessageSquare, permission: "feed.read" },
      { href: "/social/communities", key: "social-communities", label: "Comunidades", icon: Boxes, permission: "feed.read" },
      { href: "/social/boosts", key: "social-boosts", label: "Boosts", icon: Zap, permission: "feed.read" },
      { href: "/social/activity", key: "social-activity", label: "Atividade", icon: Activity, permission: "feed.read" },
      { href: "/social/investigate", key: "social-investigate", label: "Investigacao", icon: ClipboardList, permission: "audit.read" },
    ],
  },

  // ---- Plano de Controle ----
  {
    key: "governance",
    label: "Governança",
    items: [
      { href: "/audit", key: "audit", label: "Auditoria", icon: ScrollText, permission: "audit.read" },
      { href: "/administration/operators", key: "operators", label: "Operadores", icon: UserCog, permission: "user.read" },
      { href: "/administration/sessions", key: "sessions", label: "Sessões", icon: KeyRound, permission: "user.read" },
    ],
  },
];

/**
 * Telas removidas do menu, com o motivo. O CÓDIGO NÃO FOI APAGADO —
 * elas voltam assim que a dependência for resolvida, e apagar dez telas
 * funcionais por causa de um token faltando seria destrutivo.
 *
 * Auditado em 2026-08-06 chamando cada API contra a stack no Robozão.
 *
 * | Tela                          | Estado   | O que traz de volta                    |
 * |-------------------------------|----------|----------------------------------------|
 * | /social/moderation            | 401      | moderacao ainda vive no Gateway (ADR 1) |
 * | /social/reports               | 401      | idem                                    |
 * | /moderation                   | 401      | ADMIN_API_INTERNAL_TOKEN real          |
 * | /administration/users         | vazio    | ADMIN_API_INTERNAL_TOKEN real          |
 * | /publication-center           | superado | substituído por /nexus/* (mantido)     |
 * | /analytics/publications       | 404      | a rota de API nem existe               |
 * | /operations/history           | 500      | Node Agent aceitar o Control Plane     |
 * | /dlq                          | —        | superfície de DLQ no Atlas             |
 * | /auth                         | parcial  | provedor de auth reportar de verdade   |
 *
 * `/administration/operators` e `/sessions` FICARAM apesar de virem
 * vazias: elas respondem com `feature_status: "upstream_unavailable"`
 * explícito, e o operador precisa de um lugar para ver que a
 * administração de identidade existe e está degradada — diferente de
 * uma tela que simplesmente quebra.
 */
export const REMOVED_FROM_NAV = [
  // As telas de leitura do Social VOLTARAM ao menu (grupo "social"): o
  // caminho Console -> Control Plane -> Social existe. Ficaram de fora as
  // duas que dependem de moderacao/enforcement, que continua sendo dado do
  // Gateway ate a migracao descrita no ADR 0001.
  "social-reports", "social-moderation", "moderation", "users",
  "publication-center", "publication-analytics", "control-panel", "dlq",
  "authentication",
] as const;

