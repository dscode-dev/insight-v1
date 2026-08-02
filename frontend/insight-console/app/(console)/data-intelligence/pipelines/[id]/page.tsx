import { PipelineDetail } from "@/components/console/pipeline-detail";
export default function Page({ params }: { params: { id: string } }) { return <PipelineDetail pipelineId={params.id} />; }
