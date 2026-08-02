import { InvestigationWorkspace } from "@/components/console/social/workspaces";
export const dynamic = "force-dynamic";
export default function Page({ params }: { params: { type: string; id: string } }) { return <InvestigationWorkspace entityType={params.type} id={params.id} />; }
