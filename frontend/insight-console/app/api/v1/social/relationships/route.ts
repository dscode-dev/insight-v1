import { socialRead } from "@/lib/control-plane/social-bff";
import { ConsoleApiError } from "@/lib/admin-api";
import { SocialControlPlane } from "@/lib/control-plane/adapters/social";
export const dynamic = "force-dynamic";
export const GET = socialRead("social.relationship.read", "user.read", (req, ctx) => {
  const p = new URL(req.url).searchParams;
  const et = p.get("entity_type") ?? "", id = p.get("entity_id") ?? "";
  if (!et || !id) throw new ConsoleApiError(400, "entity_required");
  return SocialControlPlane.relationships(ctx, et, id);
});
