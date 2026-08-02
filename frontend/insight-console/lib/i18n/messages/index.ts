// Domain catalog assembly. Each namespace is its own file (Stage 2 — never one
// giant file). `translate` resolves locale → English → the raw key, so a missing
// translation degrades gracefully (and is visible in dev) instead of crashing.
import type { Locale } from "../config";
import { common } from "./common";
import { navigation } from "./navigation";
import { operations } from "./operations";
import { controlPanel } from "./control-panel";
import { datasetCenter } from "./dataset-center";

export const CATALOG = {
  common,
  navigation,
  operations,
  "control-panel": controlPanel,
  "dataset-center": datasetCenter,
} as const;

export type Namespace = keyof typeof CATALOG;

export type TranslateVars = Record<string, string | number>;

/** Resolve locale → English → raw key, then interpolate `{name}` placeholders. */
export function translate(
  ns: Namespace,
  locale: Locale,
  key: string,
  vars?: TranslateVars,
): string {
  const table = CATALOG[ns] as Record<Locale, Record<string, string>>;
  const raw = table[locale]?.[key] ?? table.en?.[key] ?? key;
  if (!vars) return raw;
  return raw.replace(/\{(\w+)\}/g, (match, name) =>
    name in vars ? String(vars[name]) : match,
  );
}
