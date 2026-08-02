"use client";

// Console top bar (client) — translated title + language switcher + sign out.
// CONSOLE-I18N-A. Operator data is passed from the server layout as props.
import { Badge } from "@/components/ui/badge";
import { NotificationsBell } from "@/components/notifications-bell";
import { LanguageSwitcher } from "@/components/console/language-switcher";
import { useT } from "@/lib/i18n/provider";
import { withBasePath } from "@/lib/base-path";

export function ConsoleHeader({
  role,
  displayName,
}: {
  role: string;
  displayName: string;
}) {
  const tn = useT("navigation");
  const tc = useT("common");

  return (
    <header className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-background/80 px-6 py-3 backdrop-blur">
      <span className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
        {tn("shell.header")}
      </span>
      <div className="flex items-center gap-4">
        <LanguageSwitcher />
        <NotificationsBell />
        <Badge variant="outline" className="font-mono text-[10px]">
          {role}
        </Badge>
        <span className="hidden text-sm text-foreground sm:inline">{displayName}</span>
        <form action={withBasePath("/api/auth/logout")} method="POST">
          <button
            type="submit"
            className="ix-transition rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            {tc("signOut")}
          </button>
        </form>
      </div>
    </header>
  );
}
