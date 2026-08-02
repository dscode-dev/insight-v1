import { socialRead } from "@/lib/control-plane/social-bff";
import { ConsoleApiError } from "@/lib/admin-api";
import { InvestigationService, type EntityType } from "@/lib/control-plane/services/investigation";
export const dynamic = "force-dynamic";
const TYPES = ["user","agent","post","comment","community","report"];
export const GET = socialRead("social.investigation.read", "feed.read", (req, ctx) => {
  const parts = new URL(req.url).pathname.split("/").filter(Boolean);
  const id = decodeURIComponent(parts[parts.length-1] ?? ""), type = decodeURIComponent(parts[parts.length-2] ?? "");
  if (!TYPES.includes(type)) throw new ConsoleApiError(400, "invalid_entity_type");
  return InvestigationService.investigate(ctx, type as EntityType, id);
});
