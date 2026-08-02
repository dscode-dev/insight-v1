"use client";

// CONSOLE-I18N-A — language selector (Stage 6). English / Português (Brasil).
// Changing the value persists locally and updates the whole UI immediately
// (the provider re-renders consumers — no reload).
import { Globe } from "lucide-react";

import { LOCALES, LOCALE_LABELS, type Locale } from "@/lib/i18n/config";
import { useI18n, useT } from "@/lib/i18n/provider";

export function LanguageSwitcher() {
  const { locale, setLocale } = useI18n();
  const t = useT("navigation");

  return (
    <label className="flex items-center gap-1.5" title={t("shell.language")}>
      <Globe className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
      <span className="sr-only">{t("shell.language")}</span>
      <select
        aria-label={t("shell.language")}
        value={locale}
        onChange={(e) => setLocale(e.target.value as Locale)}
        className="ix-transition cursor-pointer rounded-md border border-border bg-background px-1.5 py-1 text-xs text-foreground hover:bg-accent focus:outline-none focus:ring-1 focus:ring-ring"
      >
        {LOCALES.map((l) => (
          <option key={l} value={l}>
            {LOCALE_LABELS[l]}
          </option>
        ))}
      </select>
    </label>
  );
}
