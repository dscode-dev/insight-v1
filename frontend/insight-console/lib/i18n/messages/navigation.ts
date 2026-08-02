// Navigation + shell chrome translations. Keys mirror the stable nav ids in
// nav-config (group + item). Operational terminology is kept identical to the
// rest of the Console (Mission, Provider, Coverage, Readiness, Control Panel…).
import type { Locale } from "../config";

export const navigation: Record<Locale, Record<string, string>> = {
  en: {
    // shell
    "shell.subtitle": "Command Center",
    "shell.header": "Operational Command Center",
    "shell.language": "Language",
    // groups
    "group.operations": "Operations",
    "group.intelligence": "Intelligence",
    "group.data": "Data",
    "group.realtime": "Realtime",
    "group.administration": "Administration",
    // items
    "item.operations": "Operations Center",
    "item.control-panel": "Control Panel",
    "item.dlq": "Dead Letter Queue",
    "item.atlas-intelligence": "Atlas Intelligence",
    "item.atlas-knowledge": "Atlas Knowledge",
    "item.mission-center": "Mission Center",
    "item.dataset-center": "Dataset Center",
    "item.sources": "Sources",
    "item.tickets": "Tickets",
    "item.publication-center": "Publication Center",
    "item.publication-analytics": "Publication Analytics",
    "item.moderation": "Moderation Center",
    "item.authentication": "Authentication",
    "item.audit": "Audit Center",
    "item.users": "Users",
    "item.operators": "Operators",
    "item.sessions": "Sessions",
  },
  "pt-BR": {
    "shell.subtitle": "Centro de Comando",
    "shell.header": "Centro de Comando Operacional",
    "shell.language": "Idioma",
    "group.operations": "Operações",
    "group.intelligence": "Inteligência",
    "group.data": "Dados",
    "group.realtime": "Tempo real",
    "group.administration": "Administração",
    "item.operations": "Centro de Operações",
    "item.control-panel": "Painel de Controle",
    "item.dlq": "Fila de Mensagens Mortas",
    "item.atlas-intelligence": "Inteligência Atlas",
    "item.atlas-knowledge": "Conhecimento Atlas",
    "item.mission-center": "Centro de Missões",
    "item.dataset-center": "Centro de Datasets",
    "item.sources": "Fontes",
    "item.tickets": "Tickets",
    "item.publication-center": "Centro de Publicação",
    "item.publication-analytics": "Análise de Publicações",
    "item.moderation": "Centro de Moderação",
    "item.authentication": "Autenticação",
    "item.audit": "Centro de Auditoria",
    "item.users": "Usuários",
    "item.operators": "Operadores",
    "item.sessions": "Sessões",
  },
};
