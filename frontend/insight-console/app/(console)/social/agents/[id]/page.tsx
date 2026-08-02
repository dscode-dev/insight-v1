import { SocialAgentDetail } from "@/components/console/social/workspaces";
export const dynamic = "force-dynamic";
export default function Page({ params }: { params: { id: string } }) { return <SocialAgentDetail id={params.id} />; }
