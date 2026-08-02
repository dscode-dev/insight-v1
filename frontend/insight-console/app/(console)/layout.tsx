// Console shell — sidebar + header (Console-X redesign). Server component.
//
// Loads the operator once via currentOperator() and gates the console behind
// it. The grouped sidebar + active states are a client component (SidebarNav);
// permission filtering happens here (server) and only allowed hrefs are passed.

import { redirect } from "next/navigation";
import Link from "next/link";

import { currentOperator } from "@/lib/session";
import { hasPermission } from "@/types/auth";
import { NAV_GROUPS } from "@/components/console/nav-config";
import { SidebarNav } from "@/components/console/sidebar-nav";
import { Logo } from "@/components/brand/logo";
import { ConsoleHeader } from "@/components/console/console-header";
import { I18nProvider } from "@/lib/i18n/provider";

export default async function ConsoleLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const operator = await currentOperator();
  if (!operator) redirect("/login");

  const allowed = NAV_GROUPS.flatMap((g) => g.items)
    .filter((item) => hasPermission(operator, item.permission))
    .map((item) => item.href);

  const initials = (operator.displayName || operator.username || "OP")
    .slice(0, 2)
    .toUpperCase();

  return (
    <I18nProvider>
      <div className="grid min-h-screen grid-cols-[248px_1fr] bg-background">
        <aside className="flex flex-col border-r border-border bg-card/40">
          <div className="border-b border-border px-4 py-4">
            <Link href="/operations" className="flex items-center">
              <Logo size={30} subtitle="Command Center" wordmarkClassName="text-[15px]" />
            </Link>
          </div>
          <div className="flex-1 overflow-y-auto">
            <SidebarNav allowed={allowed} />
          </div>
          <div className="border-t border-border px-4 py-3">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-secondary text-[11px] font-semibold text-foreground ring-1 ring-inset ring-border">
                {initials}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium text-foreground">{operator.displayName}</p>
                <p className="truncate text-[10px] text-muted-foreground">{operator.role}</p>
              </div>
            </div>
          </div>
        </aside>

        <div className="flex min-w-0 flex-col">
          <ConsoleHeader role={operator.role} displayName={operator.displayName} />
          <main className="ix-page flex-1 overflow-auto p-6">{children}</main>
        </div>
      </div>
    </I18nProvider>
  );
}
