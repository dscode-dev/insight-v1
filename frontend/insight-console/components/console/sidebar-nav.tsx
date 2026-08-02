"use client";

// Sidebar navigation (Console-X) — grouped sections, section labels,
// clear active state (left indicator + surface + accent icon), hover + motion.

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";
import { NAV_GROUPS } from "@/components/console/nav-config";
import { useT } from "@/lib/i18n/provider";

export function SidebarNav({ allowed }: { allowed: string[] }) {
  const pathname = usePathname();
  const allow = new Set(allowed);
  const t = useT("navigation");

  return (
    <nav className="flex flex-col gap-5 px-3 py-3">
      {NAV_GROUPS.map((group) => {
        const items = group.items.filter((i) => allow.has(i.href));
        if (!items.length) return null;
        return (
          <div key={group.key}>
            <p className="px-2 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/70">
              {t(`group.${group.key}`)}
            </p>
            <ul className="flex flex-col gap-0.5">
              {items.map((item) => {
                const Icon = item.icon;
                const active =
                  pathname === item.href || pathname.startsWith(item.href + "/");
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "ix-transition group relative flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm",
                        active
                          ? "bg-accent font-medium text-foreground"
                          : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
                      )}
                    >
                      {/* active left indicator */}
                      <span
                        className={cn(
                          "ix-transition absolute left-0 top-1/2 h-5 -translate-y-1/2 rounded-r-full bg-primary",
                          active ? "w-0.5 opacity-100" : "w-0 opacity-0",
                        )}
                      />
                      <Icon
                        className={cn(
                          "ix-transition h-4 w-4 shrink-0",
                          active ? "text-primary" : "text-muted-foreground group-hover:text-foreground",
                        )}
                      />
                      <span className="truncate">{t(`item.${item.key}`)}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}
