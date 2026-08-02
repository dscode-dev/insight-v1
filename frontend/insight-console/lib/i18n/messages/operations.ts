// Operations Center (Operational Command Center) translations. Operational
// terminology kept consistent with the Console (Mission, Provider, Coverage,
// Readiness, Service Registry…).
import type { Locale } from "../config";

export const operations: Record<Locale, Record<string, string>> = {
  en: {
    title: "Operational Command Center",
    subtitle: "Real service, collection, ingestion and intelligence telemetry",
    refresh: "Refresh",
    degraded: "{count} telemetry source(s) degraded. Available sources remain live.",
    details: "Details",
    // tabs
    "tab.overview": "Overview",
    "tab.infrastructure": "Infra",
    "tab.missions": "Missions",
    "tab.explorer": "Explorer",
    "tab.atlas": "Atlas",
    "tab.providers": "Providers",
    "tab.timeline": "Timeline",
    "tab.coverage": "Coverage",
    "tab.intelligence": "Intelligence",
    "tab.operations": "Incidents",
    // overview
    executiveSummary: "Executive Summary",
    executiveSummarySubtitle:
      "Deterministic summary from live Explorer, Atlas, provider, mission, ticket and operations data.",
  },
  "pt-BR": {
    title: "Centro de Comando Operacional",
    subtitle: "Telemetria real de serviços, coleta, ingestão e inteligência",
    refresh: "Atualizar",
    degraded: "{count} fonte(s) de telemetria degradada(s). As fontes disponíveis permanecem ativas.",
    details: "Detalhes",
    "tab.overview": "Visão geral",
    "tab.infrastructure": "Infra",
    "tab.missions": "Missões",
    "tab.explorer": "Explorer",
    "tab.atlas": "Atlas",
    "tab.providers": "Provedores",
    "tab.timeline": "Linha do tempo",
    "tab.coverage": "Cobertura",
    "tab.intelligence": "Inteligência",
    "tab.operations": "Incidentes",
    executiveSummary: "Resumo Executivo",
    executiveSummarySubtitle:
      "Resumo determinístico a partir de dados ao vivo de Explorer, Atlas, provedores, missões, tickets e operações.",
  },
};
