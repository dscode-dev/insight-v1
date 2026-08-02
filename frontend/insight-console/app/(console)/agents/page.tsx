import { AgentsOps } from "@/components/console/agents-ops";

export const dynamic = "force-dynamic";

export default function AgentsPage() {
  return (
    <div className="mx-auto max-w-6xl">
      <AgentsOps />
    </div>
  );
}
