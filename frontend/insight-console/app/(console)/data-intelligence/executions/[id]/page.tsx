import { ExecutionDetail } from "@/components/console/execution-detail";
import { currentOperator } from "@/lib/session";
export default async function Page({ params }: { params: { id: string } }) {
  const operator = await currentOperator();
  return <ExecutionDetail executionId={params.id} superAdmin={operator?.role === "SuperAdmin"} />;
}
