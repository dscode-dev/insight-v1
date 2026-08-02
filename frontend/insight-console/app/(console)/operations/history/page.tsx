import { OperationsCenter } from "@/components/console/operations-center";

export const dynamic = "force-dynamic";

export default function ControlPanelPage() {
  return (
    <div className="mx-auto max-w-[1600px]">
      <OperationsCenter />
    </div>
  );
}
