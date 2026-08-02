import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium transition-colors",
  {
    variants: {
      variant: {
        default: "bg-secondary text-secondary-foreground",
        success: "bg-success/15 text-success",
        warning: "bg-warning/15 text-warning",
        destructive: "bg-destructive/15 text-destructive",
        outline: "border border-border text-foreground",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

/** Status pill that maps a string status → variant. Used by service-up
 * badges across Dashboard / Live Operations. */
export function StatusBadge({ status }: { status: string }) {
  const lower = status.toLowerCase();
  if (lower === "ok" || lower === "ready" || lower === "true") {
    return <Badge variant="success">● ok</Badge>;
  }
  if (lower === "down" || lower === "not_ready" || lower === "false") {
    return <Badge variant="destructive">● down</Badge>;
  }
  if (lower === "degraded") {
    return <Badge variant="warning">● degraded</Badge>;
  }
  return <Badge variant="outline">{status}</Badge>;
}
