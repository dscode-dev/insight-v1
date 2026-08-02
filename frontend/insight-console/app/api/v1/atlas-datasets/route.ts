import { requireOperator, withApiHandler } from "@/lib/api-guard";
import { atlasIntelligenceCall } from "@/lib/data-intelligence";

export const GET = withApiHandler(async (req: Request) => {
  await requireOperator();
  const url = new URL(req.url);
  return atlasIntelligenceCall(`datasets${url.search}`, "GET", undefined);
});
