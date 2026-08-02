import { DatasetCenter } from "@/components/console/dataset-center";
import { currentOperator } from "@/lib/session";
export default async function Page() {
  const operator = await currentOperator();
  return <DatasetCenter superAdmin={operator?.role === "SuperAdmin"} />;
}
