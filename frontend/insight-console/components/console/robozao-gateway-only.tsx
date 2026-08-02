import { OperationsDashboard } from "@/components/console/operations-dashboard";

export function RobozaoGatewayOnly({ title }: { title: string }) {
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        <p className="text-sm text-muted-foreground">
          This operational surface is available through Robozao Gateway only.
        </p>
      </header>
      <OperationsDashboard />
    </div>
  );
}
