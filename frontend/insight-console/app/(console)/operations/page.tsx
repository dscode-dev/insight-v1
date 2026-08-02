import { OperationalCommandCenter } from "@/components/console/operational-command-center";

export const dynamic = "force-dynamic";

export default function OperationsPage() {
  return (
    <div className="-m-3 w-[calc(100%+1.5rem)] max-w-none">
      <OperationalCommandCenter />
    </div>
  );
}
