// CONSOLE-I18N-A — internationalization foundation.
//
// V1 locales: English + Portuguese (Brazil). Detection order:
//   stored preference → system language (pt-* → pt-BR, en-* → en) → fallback en.
// The catalog is split by domain (see ./messages) — never one giant file.

export const LOCALES = ["en", "pt-BR"] as const;
export type Locale = (typeof LOCALES)[number];

export const DEFAULT_LOCALE: Locale = "en";

export const LOCALE_LABELS: Record<Locale, string> = {
  en: "English",
  "pt-BR": "Português (Brasil)",
};

/** localStorage key for the persisted preference. */
export const LOCALE_STORAGE_KEY = "console.locale";

/** Narrow an arbitrary string to a supported Locale, or null. */
export function normalizeLocale(value: string | null | undefined): Locale | null {
  if (!value) return null;
  return (LOCALES as readonly string[]).includes(value) ? (value as Locale) : null;
}

/** Map the browser/system language to a supported locale. Fallback → English. */
export function detectSystemLocale(): Locale {
  if (typeof navigator === "undefined") return DEFAULT_LOCALE;
  const lang = (navigator.language || "").toLowerCase();
  if (lang.startsWith("pt")) return "pt-BR";
  return DEFAULT_LOCALE; // en-* and everything else
}
