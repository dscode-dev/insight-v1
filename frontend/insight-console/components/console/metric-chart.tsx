import { cn } from "@/lib/utils";

export type MetricPoint = { label: string; value: number; detail?: string };

export function MetricBars({
  points,
  tone = "bg-primary",
  empty = "No measurements reported by the runtime.",
}: {
  points: MetricPoint[];
  tone?: string;
  empty?: string;
}) {
  const max = Math.max(0, ...points.map((point) => point.value));
  if (!points.length) {
    return <p className="text-xs text-muted-foreground">{empty}</p>;
  }
  return (
    <div className="space-y-2">
      {points.map((point) => (
        <div key={point.label} className="grid grid-cols-[8rem_1fr_auto] items-center gap-2 text-xs">
          <span className="truncate" title={point.label}>{point.label}</span>
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div
              className={cn("h-full rounded-full", tone)}
              style={{ width: `${max ? Math.max(2, point.value / max * 100) : 0}%` }}
            />
          </div>
          <span className="min-w-12 text-right font-mono text-muted-foreground" title={point.detail}>
            {point.value.toLocaleString()}
          </span>
        </div>
      ))}
    </div>
  );
}

export function DistributionBar({
  value,
  max = 1,
  tone = "bg-primary",
}: {
  value: number;
  max?: number;
  tone?: string;
}) {
  return (
    <div className="h-2 overflow-hidden rounded-full bg-muted">
      <div
        className={cn("h-full rounded-full", tone)}
        style={{ width: `${Math.min(100, Math.max(0, max ? value / max * 100 : 0))}%` }}
      />
    </div>
  );
}
