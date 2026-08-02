"use client";

// CONSOLE-I18N-A — runtime i18n provider. Holds the active locale, persists the
// preference locally, detects the system language on first access, and switches
// the entire UI immediately (no reload). All translation logic lives here — no
// component re-implements lookups.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  DEFAULT_LOCALE,
  detectSystemLocale,
  LOCALE_STORAGE_KEY,
  normalizeLocale,
  type Locale,
} from "./config";
import { translate, type Namespace, type TranslateVars } from "./messages";

type I18nContextValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (ns: Namespace, key: string, vars?: TranslateVars) => string;
};

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({ children }: { children: React.ReactNode }) {
  // SSR + first client render use the default (English) so hydration matches;
  // the effect below swaps to the stored/system locale right after mount.
  const [locale, setLocaleState] = useState<Locale>(DEFAULT_LOCALE);

  useEffect(() => {
    const stored = normalizeLocale(
      typeof window !== "undefined" ? window.localStorage.getItem(LOCALE_STORAGE_KEY) : null,
    );
    const initial = stored ?? detectSystemLocale();
    setLocaleState(initial);
    document.documentElement.lang = initial;
  }, []);

  const setLocale = useCallback((next: Locale) => {
    try {
      window.localStorage.setItem(LOCALE_STORAGE_KEY, next);
    } catch {
      /* storage unavailable — switch is still applied in-memory */
    }
    document.documentElement.lang = next;
    setLocaleState(next);
  }, []);

  const t = useCallback(
    (ns: Namespace, key: string, vars?: TranslateVars) => translate(ns, locale, key, vars),
    [locale],
  );

  const value = useMemo<I18nContextValue>(
    () => ({ locale, setLocale, t }),
    [locale, setLocale, t],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within <I18nProvider>");
  return ctx;
}

export function useLocale(): Locale {
  return useI18n().locale;
}

/** Namespaced translator: `const t = useT("operations"); t("title")`. */
export function useT(ns: Namespace): (key: string, vars?: TranslateVars) => string {
  const { t } = useI18n();
  return useCallback((key: string, vars?: TranslateVars) => t(ns, key, vars), [t, ns]);
}
