import Image from "next/image";

import { withBasePath } from "@/lib/base-path";
import { cn } from "@/lib/utils";

// Insight brand mark — the app-icon logo + the "Insight" wordmark.
// The logo PNG is pre-processed with transparent rounded corners
// (public/insight-logo.png). The wordmark uses the tech display weight of
// Space Grotesk with tight tracking for a distinct, modern identity.

export function InsightWordmark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "font-sans font-semibold tracking-tight bg-gradient-to-r from-white to-slate-400 bg-clip-text text-transparent",
        className,
      )}
    >
      Insight
    </span>
  );
}

export function Logo({
  size = 28,
  wordmark = true,
  subtitle,
  className,
  wordmarkClassName,
}: {
  size?: number;
  wordmark?: boolean;
  subtitle?: string;
  className?: string;
  wordmarkClassName?: string;
}) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <Image
        src={withBasePath("/insight-logo.png")}
        alt="Insight"
        width={size}
        height={size}
        priority
        className="rounded-[22%] ring-1 ring-inset ring-white/10"
      />
      {wordmark ? (
        <span className="flex flex-col leading-none">
          <InsightWordmark className={cn("text-base", wordmarkClassName)} />
          {subtitle ? (
            <span className="mt-0.5 text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
              {subtitle}
            </span>
          ) : null}
        </span>
      ) : null}
    </div>
  );
}
