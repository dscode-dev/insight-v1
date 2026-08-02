import { LlmOps } from "@/components/console/llm-ops";

export const dynamic = "force-dynamic";

export default function LLMOperationsPage() {
  return (
    <div className="mx-auto max-w-6xl">
      <LlmOps />
    </div>
  );
}
